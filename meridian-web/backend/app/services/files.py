"""Job-хендлеры для файлов (§15): асинхронное физическое удаление из S3."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from ..config import get_settings
from ..database import async_session
from ..models.file import FileRecord
from .jobs import enqueue
from . import s3

logger = logging.getLogger("meridian.files")


async def handle_file_physical_delete(payload: dict) -> None:
    """Удалить объект из S3 (идемпотентно) и пометить запись deleted."""
    key = payload["object_key"]
    await s3.delete_object(key)
    async with async_session() as db:
        rec = (
            await db.execute(select(FileRecord).where(FileRecord.object_key == key))
        ).scalar_one_or_none()
        if rec:
            rec.status = "deleted"
            if not rec.deleted_at:
                rec.deleted_at = datetime.utcnow()
            await db.commit()
    logger.info("file physically deleted: %s", key)


async def sweep_abandoned_pending() -> int:
    """Закрыть брошенные upload-сессии: записи pending, по которым не пришёл confirm.

    Браузерный PUT мог упасть (обрыв, 413 на прокси, закрытая вкладка) — тогда строка
    остаётся pending навсегда и в списках не видна (они отдают только active). Порог
    берём с большим запасом относительно presign TTL, чтобы не убить живую заливку.
    Физическое удаление идемпотентно: объекта может и не быть.
    """
    hours = get_settings().pending_upload_ttl_hours
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    async with async_session() as db:
        rows = (
            await db.execute(
                select(FileRecord).where(
                    FileRecord.status == "pending",
                    FileRecord.created_at <= cutoff,
                )
            )
        ).scalars().all()
        for rec in rows:
            rec.status = "deleted"
            rec.deleted_at = datetime.utcnow()
            await enqueue(db, "file_physical_delete", {"object_key": rec.object_key})
        if rows:
            await db.commit()
        return len(rows)
