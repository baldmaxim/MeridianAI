# -*- coding: utf-8 -*-
"""Десктоп: распознавание аудиофайла на сервере (ElevenLabs Scribe v3) через batch-задачу.

Тот же конвейер, что у сайта (api/batch.py, задача `batch_transcribe`): загрузка в S3 по
presigned URL, подтверждение, опрос результата. Здесь — только вход по токену устройства и
идемпотентное подтверждение: приложение может повторить запрос после потери ответа.

Роутер подключается в конце api/desktop.py (поздний импорт: `Device` берётся оттуда же).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.batch_job import BatchJob
from ..models.file import FileRecord
from ..schemas.batch import (
    BatchJobDetailResponse,
    BatchJobResponse,
    ConfirmUploadRequest,
    UploadSessionRequest,
    UploadSessionResponse,
)
from .batch import confirm_upload, create_upload_session, get_batch_job
from .desktop import Device

router = APIRouter()


class TranscriptionUploadRequest(BaseModel):
    filename: str
    size: int = Field(ge=1)


class TranscriptionConfirmRequest(BaseModel):
    # Число говорящих; None — определить автоматически.
    max_speakers: Optional[int] = Field(None, ge=2, le=6)


@router.post("/transcriptions/upload-session", response_model=UploadSessionResponse)
async def transcriptions_upload_session(
    data: TranscriptionUploadRequest, response: Response, auth: Device,
    db: AsyncSession = Depends(get_db),
):
    """Presigned PUT для аудиофайла. Проверки S3, формата и размера — как у сайта."""
    # в ответе presigned URL с подписью — не кэшируем
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return await create_upload_session(
        UploadSessionRequest(filename=data.filename, size=data.size), user=auth.user, db=db,
    )


@router.post("/transcriptions/{file_id}/confirm", response_model=BatchJobResponse)
async def transcriptions_confirm(
    file_id: int, auth: Device, data: Optional[TranscriptionConfirmRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """Подтвердить загрузку и поставить распознавание. Повтор отдаёт ту же задачу, без новой в очереди."""
    rec = (await db.execute(
        select(FileRecord).where(
            FileRecord.id == file_id, FileRecord.user_id == auth.user.id,
            FileRecord.purpose == "batch_audio",
        )
    )).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    existing = (await db.execute(
        select(BatchJob).where(BatchJob.user_id == auth.user.id, BatchJob.file_path == rec.object_key)
        .order_by(BatchJob.id)
    )).scalars().first()
    if existing is not None:
        return existing

    return await confirm_upload(
        file_id, ConfirmUploadRequest(max_speakers=data.max_speakers if data else None),
        user=auth.user, db=db,
    )


@router.get("/transcriptions/{job_id}", response_model=BatchJobDetailResponse)
async def transcriptions_get(job_id: int, auth: Device, db: AsyncSession = Depends(get_db)):
    """Статус и результат распознавания (текст, реплики по говорящим). Чужая задача — 404."""
    return await get_batch_job(job_id, user=auth.user, db=db)
