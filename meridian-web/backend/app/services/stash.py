"""Мини-облако: фоновый sweep истёкших файлов (TTL авто-удаление).

Soft-delete строк files с purpose="stash", у которых expires_at прошёл, и постановка
физического удаления из S3 в очередь (file_physical_delete). Вызывается из
_session_cleanup_loop в app/main.py.
"""

import logging
from datetime import datetime

from sqlalchemy import select

from ..database import async_session
from ..models.file import FileRecord
from .jobs import enqueue

logger = logging.getLogger("meridian.stash")


async def sweep_expired_stash() -> int:
    """Пометить истёкшие stash-файлы deleted и поставить физ. удаление. Вернуть число."""
    now = datetime.utcnow()
    async with async_session() as db:
        rows = (
            await db.execute(
                select(FileRecord).where(
                    FileRecord.purpose == "stash",
                    FileRecord.status.in_(("pending", "active")),
                    FileRecord.expires_at.is_not(None),
                    FileRecord.expires_at <= now,
                )
            )
        ).scalars().all()
        for rec in rows:
            rec.status = "deleted"
            rec.deleted_at = now
            await enqueue(db, "file_physical_delete", {"object_key": rec.object_key})
        if rows:
            await db.commit()
        return len(rows)
