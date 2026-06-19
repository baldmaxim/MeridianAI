"""Схемы предпросмотра Context Pack (Этап 6)."""

from typing import Any

from pydantic import BaseModel


class ContextBlockPreviewOut(BaseModel):
    kind: str
    title: str
    enabled: bool
    reason: str | None = None
    chars: int
    estimated_tokens: int
    source_count: int = 0
    max_chars: int | None = None
    truncated: bool = False
    content_preview: str
    meta: dict[str, Any] = {}


class ContextPackPreviewOut(BaseModel):
    meeting_id: int
    mode: str
    query_text: str
    total_chars: int
    estimated_tokens: int
    max_chars: int | None = None
    truncated: bool = False
    blocks: list[ContextBlockPreviewOut]
    # Этап 9.8: текущий авторитетный источник транскрипта (single|multi_channel) и эпохи
    transcription_source: str | None = None
    transcription_epochs_count: int = 0
    transcription_fallback_used: bool = False
