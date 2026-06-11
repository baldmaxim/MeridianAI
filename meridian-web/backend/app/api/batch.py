"""Batch audio transcription and protocol generation API."""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.batch_job import BatchJob
from ..schemas.batch import BatchJobResponse, BatchJobDetailResponse
from ..services.jobs import enqueue
from ..core.batch.utils import format_transcription_txt
from ..config import get_settings

logger = logging.getLogger("meridian.batch")

router = APIRouter()

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus", ".webm"}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


@router.post("/upload", response_model=BatchJobResponse)
async def upload_batch_audio(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Формат {ext} не поддерживается. Допустимые: {', '.join(ALLOWED_EXTENSIONS)}")

    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / "batch" / str(user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
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
    )
    db.add(job)
    await db.flush()
    # outbox: задача в очередь в той же транзакции, что и BatchJob (§16)
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

    # Delete files
    for path in [job.file_path, job.compressed_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

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
