# -*- coding: utf-8 -*-
"""Ключ объекта S3 → presigned GET на аудио (для проигрывания/скачивания)."""

from dataclasses import dataclass

from ..config import get_settings
from . import s3


@dataclass(frozen=True)
class AudioLink:
    # presigned URL — секрет: не логировать, не писать в audit и тексты ошибок
    url: str
    content_type: str | None
    size: int | None
    expires_in: int


async def presign_audio(key: str, download_name: str | None = None) -> AudioLink | None:
    """Presigned GET или None: S3 выключен, ключ пуст или объекта нет в хранилище."""
    settings = get_settings()
    if not key or not settings.s3_enabled:
        return None
    meta = await s3.head_object(key)
    if not meta:
        return None
    ttl = settings.batch_audio_presign_ttl
    url = s3.presign_get(key, ttl=ttl, download_name=download_name)
    return AudioLink(url=url, content_type=meta.get("content_type"), size=meta.get("size"),
                     expires_in=ttl)
