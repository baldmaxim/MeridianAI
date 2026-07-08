"""Batch audio transcription and protocol generation API."""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response, FileResponse
from starlette.background import BackgroundTask
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
    BatchSegment,
    UploadSessionRequest,
    UploadSessionResponse,
    ConfirmUploadRequest,
    ClipRequest,
)
from ..services.jobs import enqueue
from ..services import s3
from ..core.batch.utils import format_transcription_txt, group_words_by_speaker
from ..config import get_settings

import re


def _norm_speaker(raw: str) -> str:
    """'Speaker_speaker_0' → 'Спикер 1' (диаризация ElevenLabs → человекочитаемо)."""
    m = re.search(r"(\d+)\s*$", raw or "")
    return f"Спикер {int(m.group(1)) + 1}" if m else (raw or "Спикер")

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


@router.post("/from-stash/{file_id}", response_model=BatchJobResponse)
async def create_from_stash(
    file_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Распознать уже загруженный в мини-облако (stash) аудиофайл.

    Копируем объект в собственный batch_audio-ключ (независимое удаление задачи vs файла),
    заводим FileRecord+BatchJob и ставим задачу транскрипции.
    """
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(503, "S3-хранилище не настроено")

    rec = (
        await db.execute(
            select(FileRecord).where(FileRecord.id == file_id, FileRecord.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not rec or rec.purpose != "stash" or rec.status != "active":
        raise HTTPException(404, "Файл не найден")

    ext = Path(rec.original_name or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Не аудиофайл. Допустимые форматы: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    new_key = s3.object_key(user.id, "batch_audio", rec.original_name)
    await s3.copy_object(rec.object_key, new_key)

    file_rec = FileRecord(
        user_id=user.id,
        object_key=new_key,
        original_name=rec.original_name,
        size=rec.size,
        mime=rec.mime,
        purpose="batch_audio",
        status="active",
    )
    db.add(file_rec)
    job = BatchJob(
        user_id=user.id,
        status="uploaded",
        original_filename=rec.original_name,
        original_size=rec.size or 0,
        file_path=new_key,
    )
    db.add(job)
    await db.flush()
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

    resp = BatchJobDetailResponse.model_validate(job)
    # Диаризация: реплики (спикер + таймкоды) из word-level transcription_json
    if job.transcription_json:
        try:
            words = (json.loads(job.transcription_json) or {}).get("words") or []
            resp.segments = [
                BatchSegment(speaker=_norm_speaker(s.speaker), start=s.start, end=s.end, text=s.text)
                for s in group_words_by_speaker(words)
            ]
        except Exception:
            resp.segments = []
    return resp


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


@router.get("/jobs/{job_id}/audio-url")
async def get_job_audio_url(
    job_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Presigned GET на исходное аудио задачи — для проигрывания/скачивания в браузере.

    Аудио в S3 поддерживает Range-запросы → плеер стримит и перематывает без полной загрузки.
    """
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(503, "S3-хранилище не настроено")
    result = await db.execute(
        select(BatchJob).where(BatchJob.id == job_id, BatchJob.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job or not job.file_path:
        raise HTTPException(404, "Аудио недоступно")
    meta = await s3.head_object(job.file_path)
    if not meta:
        raise HTTPException(404, "Аудио недоступно")
    name = (job.original_filename or "audio").replace('"', "").replace("\r", "").replace("\n", "")
    # presigned URL — секрет, НЕ логировать. Длинный TTL — чтобы перемотка не отваливалась.
    url = s3.presign_get(job.file_path, ttl=settings.batch_audio_presign_ttl, download_name=name)
    return {"url": url, "content_type": meta.get("content_type"), "size": meta.get("size")}


@router.post("/jobs/{job_id}/clip")
async def clip_audio(
    job_id: int,
    data: ClipRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Серверная нарезка фрагмента через ffmpeg (быстрый seek по Range, без скачивания целого)."""
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(503, "S3-хранилище не настроено")
    result = await db.execute(
        select(BatchJob).where(BatchJob.id == job_id, BatchJob.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if not job or not job.file_path:
        raise HTTPException(404, "Аудио недоступно")

    start = max(0.0, float(data.start))
    end = float(data.end)
    if not (end > start):
        raise HTTPException(400, "Некорректный интервал")
    dur = min(end - start, float(settings.batch_clip_max_seconds))

    meta = await s3.head_object(job.file_path)
    if not meta:
        raise HTTPException(404, "Аудио недоступно")

    src_url = s3.presign_get(job.file_path, ttl=1800)  # НЕ логировать
    tmpdir = tempfile.mkdtemp(prefix="meridian_clip_")
    out_path = os.path.join(tmpdir, "clip.mp3")
    args = [
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", src_url, "-t", f"{dur:.3f}",
        "-vn", "-ac", "1", "-c:a", "libmp3lame", "-q:a", "5", out_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.batch_clip_timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(504, "Нарезка заняла слишком долго")

    if proc.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        logger.error("ffmpeg clip failed rc=%s: %s", proc.returncode, (stderr or b"")[:300])
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(500, "Не удалось вырезать фрагмент")

    stem = Path(job.original_filename or "audio").stem
    fname = f"{stem}_{int(start)}-{int(end)}.mp3".replace('"', "").replace("\r", "").replace("\n", "")
    return FileResponse(
        out_path, media_type="audio/mpeg", filename=fname,
        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True),
    )


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
