"""Batch audio transcription and protocol generation API."""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.batch_job import BatchJob
from ..models.file import FileRecord
from ..schemas.batch import (
    BatchJobResponse,
    BatchJobDetailResponse,
    UploadSessionRequest,
    UploadSessionResponse,
    ConfirmUploadRequest,
)
from ..services.jobs import enqueue
from ..services import s3
from ..core.batch.utils import format_transcription_txt
from ..config import get_settings

logger = logging.getLogger("meridian.batch")

router = APIRouter()

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus", ".webm"}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


@router.post("/upload", response_model=BatchJobResponse)
async def upload_batch_audio(
    file: UploadFile = File(...),
    meeting_id: Optional[int] = Form(None),
    kind: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fallback-загрузка через backend, когда S3 не настроен.
    При настроенном S3 фронт использует upload-session/confirm (§15)."""
    settings = get_settings()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Формат {ext} не поддерживается. Допустимые: {', '.join(ALLOWED_EXTENSIONS)}")

    upload_dir = Path(settings.upload_dir) / "batch" / str(user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{Path(file.filename or 'audio').name}"
    file_path = upload_dir / safe_name

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"Файл слишком большой (макс. {MAX_FILE_SIZE // 1024 // 1024}MB)")
    with open(file_path, "wb") as f:
        f.write(content)

    job = BatchJob(
        user_id=user.id,
        status="uploaded",
        original_filename=file.filename or "unknown",
        original_size=len(content),
        file_path=str(file_path),
        kind=("gap_fill" if kind == "gap_fill" else None),
        meeting_id=meeting_id,
    )
    db.add(job)
    await db.flush()
    await enqueue(db, "batch_transcribe", {"batch_job_id": job.id})
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/upload-session", response_model=UploadSessionResponse)
async def create_upload_session(
    data: UploadSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§15: выдать presigned PUT URL. Браузер грузит файл напрямую в S3."""
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(503, "S3-хранилище не настроено")
    ext = Path(data.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Формат {ext} не поддерживается. Допустимые: {', '.join(ALLOWED_EXTENSIONS)}")
    if data.size and data.size > MAX_FILE_SIZE:
        raise HTTPException(400, f"Файл слишком большой (макс. {MAX_FILE_SIZE // 1024 // 1024}MB)")

    key = s3.object_key(user.id, "batch_audio", data.filename)
    rec = FileRecord(
        user_id=user.id,
        object_key=key,
        original_name=data.filename or "unknown",
        size=data.size,
        purpose="batch_audio",
        status="pending",
        meeting_id=data.meeting_id,  # Задача 5: привязка дозаписи к встрече
    )
    db.add(rec)
    await db.flush()
    upload_url = s3.presign_put(key)
    await db.commit()
    return UploadSessionResponse(file_id=rec.id, upload_url=upload_url)


@router.post("/confirm/{file_id}", response_model=BatchJobResponse)
async def confirm_upload(
    file_id: int,
    data: Optional[ConfirmUploadRequest] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§15: проверить объект в S3, активировать запись, поставить задачу обработки."""
    rec = (
        await db.execute(
            select(FileRecord).where(FileRecord.id == file_id, FileRecord.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not rec or rec.purpose != "batch_audio":
        raise HTTPException(404, "Файл не найден")

    meta = await s3.head_object(rec.object_key)
    if not meta:
        raise HTTPException(400, "Объект не загружен в хранилище")

    rec.status = "active"
    rec.size = meta["size"]
    rec.mime = meta.get("content_type")

    # Задача 5: kind/meeting_id из тела (приоритет) или из FileRecord (upload-session)
    kind = "gap_fill" if (data and data.kind == "gap_fill") else None
    meeting_id = (data.meeting_id if data and data.meeting_id is not None else rec.meeting_id)

    job = BatchJob(
        user_id=user.id,
        status="uploaded",
        original_filename=rec.original_name,
        original_size=meta["size"] or 0,
        file_path=rec.object_key,  # теперь это S3-ключ, не локальный путь
        kind=kind,
        meeting_id=meeting_id,
    )
    db.add(job)
    await db.flush()
    # outbox: задача в очередь в той же транзакции (§16)
    await enqueue(db, "batch_transcribe", {"batch_job_id": job.id})
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/jobs", response_model=List[BatchJobResponse])
async def list_batch_jobs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BatchJob)
        .where(BatchJob.user_id == user.id)
        .order_by(BatchJob.created_at.desc())
    )
    return result.scalars().all()


@router.get("/jobs/{job_id}", response_model=BatchJobDetailResponse)
async def get_batch_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BatchJob).where(BatchJob.id == job_id, BatchJob.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return job


@router.delete("/jobs/{job_id}")
async def delete_batch_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BatchJob).where(BatchJob.id == job_id, BatchJob.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Задача не найдена")

    # §15: soft delete файла + асинхронное физическое удаление из S3
    rec = (
        await db.execute(select(FileRecord).where(FileRecord.object_key == job.file_path))
    ).scalar_one_or_none()
    if rec and rec.status != "deleted":
        rec.status = "deleted"
        rec.deleted_at = datetime.utcnow()
        await enqueue(db, "file_physical_delete", {"object_key": rec.object_key})

    await db.delete(job)
    await db.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/download/{download_type}")
async def download_batch_result(
    job_id: int,
    download_type: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BatchJob).where(BatchJob.id == job_id, BatchJob.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Задача не найдена")

    stem = Path(job.original_filename).stem

    if download_type == "transcript_txt":
        if not job.transcription_json:
            raise HTTPException(400, "Транскрипция недоступна")
        data = json.loads(job.transcription_json)
        content = format_transcription_txt(data)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}_transcript.txt"'},
        )

    elif download_type == "transcript_json":
        if not job.transcription_json:
            raise HTTPException(400, "Транскрипция недоступна")
        return Response(
            content=job.transcription_json.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}_transcript.json"'},
        )

    elif download_type == "protocol_txt":
        if not job.protocol_markdown:
            raise HTTPException(400, "Протокол недоступен")
        return Response(
            content=job.protocol_markdown.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}_protocol.txt"'},
        )

    elif download_type == "protocol_json":
        if not job.protocol_json:
            raise HTTPException(400, "Протокол JSON недоступен")
        return Response(
            content=job.protocol_json.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}_protocol.json"'},
        )

    raise HTTPException(400, f"Неизвестный тип: {download_type}")
