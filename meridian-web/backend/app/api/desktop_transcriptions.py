# -*- coding: utf-8 -*-
"""Десктоп: распознавание аудиофайла на сервере (ElevenLabs Scribe v3) через batch-задачу.

Тот же конвейер, что у сайта (api/batch.py, задача `batch_transcribe`): загрузка в S3 по
presigned URL, подтверждение, опрос результата. Здесь — только вход по токену устройства и
идемпотентное подтверждение: приложение может повторить запрос после потери ответа.

Роутер подключается в конце api/desktop.py (поздний импорт: `Device` берётся оттуда же).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.batch_job import BatchJob
from ..models.file import FileRecord
from ..core.http_files import safe_download_name
from ..schemas.desktop import DesktopAudioUrl
from ..services.audio_links import presign_audio
from ..schemas.batch import (
    BatchJobDetailResponse,
    BatchJobResponse,
    ConfirmUploadRequest,
    UploadSessionRequest,
    UploadSessionResponse,
)
from .batch import _job_access, confirm_upload, create_upload_session, get_batch_job, list_batch_jobs
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


@router.get("/transcriptions", response_model=List[BatchJobResponse])
async def transcriptions_list(auth: Device, db: AsyncSession = Depends(get_db)):
    """Все записи пользователя (сайт, другие ПК), новые первыми — без текста; текст отдаёт GET по id.

    Без `gap_fill`: это внутренняя офлайн-дозапись встречи, а не загруженный файл.
    """
    jobs = await list_batch_jobs(scope="mine", user=auth.user, db=db)
    gap_ids = set((await db.execute(
        select(BatchJob.id).where(BatchJob.user_id == auth.user.id, BatchJob.kind == "gap_fill")
    )).scalars().all())
    return [j for j in jobs if j.id not in gap_ids]


@router.get("/transcriptions/{job_id}", response_model=BatchJobDetailResponse)
async def transcriptions_get(job_id: int, auth: Device, db: AsyncSession = Depends(get_db)):
    """Статус и результат распознавания (текст, реплики по говорящим). Чужая задача — 404."""
    return await get_batch_job(job_id, user=auth.user, db=db)


@router.get("/transcriptions/{job_id}/audio", response_model=DesktopAudioUrl)
async def transcriptions_audio(job_id: int, auth: Device, db: AsyncSession = Depends(get_db)):
    """Presigned GET на исходное аудио записи. Чужая задача — 404; нет аудио — 404 audio_not_found."""
    job = (await db.execute(
        select(BatchJob).where(BatchJob.id == job_id, _job_access(auth.user))
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    link = await presign_audio(job.file_path, download_name=safe_download_name(job.original_filename or "audio"))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="audio_not_found")
    return DesktopAudioUrl(url=link.url, source="batch", expires_in=link.expires_in)
