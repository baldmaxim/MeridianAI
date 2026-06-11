"""Job-хендлеры для файлов (§15): асинхронное физическое удаление из S3."""

import logging
from datetime import datetime

from sqlalchemy import select

from ..database import async_session
from ..models.file import FileRecord
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
