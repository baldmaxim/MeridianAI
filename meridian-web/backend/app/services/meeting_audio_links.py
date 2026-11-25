# -*- coding: utf-8 -*-
"""Части записи встречи для проигрывания на сайте: presigned GET по источникам.

Порядок источников: распознанная запись (batch, без gap_fill) → архив ПК
(mixed → system → mic) → архив живой записи с сайта (все части по возрастанию id).
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.http_files import safe_download_name
from ..models.batch_job import BatchJob
from ..models.file import FileRecord
from .audio_links import presign_audio

AUDIO_CHANNEL_PRIORITY = ("mixed", "system", "mic")
LIVE_ARCHIVE_PREFIX = "meeting_"


@dataclass(frozen=True)
class MeetingAudioPartLink:
    # url — presigned, секрет: не логировать
    url: str
    source: str
    expires_in: int
    name: str


async def list_meeting_audio_parts(db: AsyncSession, meeting_id: int) -> list[MeetingAudioPartLink]:
    """Части записи встречи; пусто — аудио нет, S3 выключен или объектов нет в хранилище."""
    job = (await db.execute(
        select(BatchJob).where(
            BatchJob.meeting_id == meeting_id, BatchJob.file_path != "",
            BatchJob.kind.is_(None) | (BatchJob.kind != "gap_fill"),
        ).order_by(BatchJob.id.desc())
    )).scalars().first()
    if job is not None:
        name = safe_download_name(job.original_filename or "audio")
        link = await presign_audio(job.file_path, download_name=name)
        if link is not None:
            return [MeetingAudioPartLink(link.url, "batch", link.expires_in, name)]

    records = (await db.execute(
        select(FileRecord).where(
            FileRecord.meeting_id == meeting_id, FileRecord.purpose == "meeting_audio",
            FileRecord.status == "active",
        ).order_by(FileRecord.id.desc())
    )).scalars().all()
    for channel in AUDIO_CHANNEL_PRIORITY:
        for rec in records:
            if not rec.original_name.startswith(f"{channel}_"):
                continue
            name = safe_download_name(rec.original_name)
            link = await presign_audio(rec.object_key, download_name=name)
            if link is not None:
                return [MeetingAudioPartLink(link.url, channel, link.expires_in, name)]

    parts: list[MeetingAudioPartLink] = []
    live = sorted(
        (r for r in records if r.original_name.startswith(LIVE_ARCHIVE_PREFIX)),
        key=lambda r: r.id,
    )
    for rec in live:
        link = await presign_audio(rec.object_key, download_name=safe_download_name(rec.original_name))
        if link is not None:
            parts.append(MeetingAudioPartLink(link.url, "live", link.expires_in, f"Часть {len(parts) + 1}"))
    return parts
