"""Мини-облако: личное временное хранилище файлов (обмен между устройствами).

Presigned-S3 поток (§15): браузер грузит/скачивает файл напрямую в S3, backend не
проксирует байты. Все запросы scoped по user_id — каждый видит только свои файлы.
Файлы авто-удаляются через stash_retention_days (плюс ручное удаление).
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.file import FileRecord
from ..schemas.stash import (
    StashUploadSessionRequest,
    StashUploadSessionResponse,
    StashFileResponse,
    StashDownloadUrlResponse,
    StashDownloadItem,
)
from ..services.jobs import enqueue
from ..services import s3
from ..config import get_settings

logger = logging.getLogger("meridian.stash")

router = APIRouter()

PURPOSE = "stash"


def _safe_download_name(name: str) -> str:
    """Имя для Content-Disposition: basename без управляющих символов/кавычек."""
    base = os.path.basename(name or "")
    base = base.replace('"', "").replace("\r", "").replace("\n", "").strip()
    return base[:200] or "download"


@router.post("/upload-session", response_model=StashUploadSessionResponse)
async def create_upload_session(
    data: StashUploadSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выдать presigned PUT URL. Браузер грузит файл напрямую в S3."""
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(503, "S3-хранилище не настроено")
    if not (data.filename or "").strip():
        raise HTTPException(400, "Имя файла обязательно")
    max_bytes = settings.stash_max_upload_mb * 1024 * 1024
    if data.size and data.size > max_bytes:
        raise HTTPException(400, f"Файл слишком большой (макс. {settings.stash_max_upload_mb}MB)")

    key = s3.object_key(user.id, PURPOSE, data.filename)
    rec = FileRecord(
        user_id=user.id,
        object_key=key,
        original_name=(data.filename or "unknown")[:500],
        size=data.size,
        purpose=PURPOSE,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(days=settings.stash_retention_days),
    )
    db.add(rec)
    await db.flush()
    upload_url = s3.presign_put(key)
    await db.commit()
    return StashUploadSessionResponse(file_id=rec.id, upload_url=upload_url)


@router.post("/confirm/{file_id}", response_model=StashFileResponse)
async def confirm_upload(
    file_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Проверить объект в S3 и активировать запись."""
    rec = (
        await db.execute(
            select(FileRecord).where(FileRecord.id == file_id, FileRecord.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not rec or rec.purpose != PURPOSE:
        raise HTTPException(404, "Файл не найден")

    meta = await s3.head_object(rec.object_key)
    if not meta:
        raise HTTPException(400, "Объект не загружен в хранилище")

    rec.status = "active"
    rec.size = meta["size"]
    rec.mime = meta.get("content_type")
    await db.commit()
    await db.refresh(rec)
    return rec


@router.get("", response_model=List[StashFileResponse])
async def list_files(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FileRecord)
        .where(
            FileRecord.user_id == user.id,
            FileRecord.purpose == PURPOSE,
            FileRecord.status == "active",
        )
        .order_by(FileRecord.created_at.desc())
    )
    return result.scalars().all()


@router.get("/download-urls", response_model=List[StashDownloadItem])
async def get_all_download_urls(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Presigned GET на ВСЕ активные файлы пользователя (для «Скачать все» в папку)."""
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(503, "S3-хранилище не настроено")
    rows = (
        await db.execute(
            select(FileRecord)
            .where(
                FileRecord.user_id == user.id,
                FileRecord.purpose == PURPOSE,
                FileRecord.status == "active",
            )
            .order_by(FileRecord.created_at.desc())
        )
    ).scalars().all()
    # presigned URL — секреты, НЕ логировать
    return [
        StashDownloadItem(
            id=r.id,
            original_name=r.original_name,
            url=s3.presign_get(r.object_key, download_name=_safe_download_name(r.original_name)),
        )
        for r in rows
    ]


@router.get("/{file_id}/download-url", response_model=StashDownloadUrlResponse)
async def get_download_url(
    file_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Presigned GET URL для скачивания оригинала (с именем через Content-Disposition)."""
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(503, "S3-хранилище не настроено")
    rec = (
        await db.execute(
            select(FileRecord).where(FileRecord.id == file_id, FileRecord.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not rec or rec.purpose != PURPOSE or rec.status != "active":
        raise HTTPException(404, "Файл не найден")

    # presigned URL — секрет, НЕ логировать (§18)
    url = s3.presign_get(rec.object_key, download_name=_safe_download_name(rec.original_name))
    return StashDownloadUrlResponse(url=url)


@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = (
        await db.execute(
            select(FileRecord).where(FileRecord.id == file_id, FileRecord.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not rec or rec.purpose != PURPOSE:
        raise HTTPException(404, "Файл не найден")

    if rec.status != "deleted":
        rec.status = "deleted"
        rec.deleted_at = datetime.utcnow()
        await enqueue(db, "file_physical_delete", {"object_key": rec.object_key})
    await db.commit()
    return {"ok": True}
