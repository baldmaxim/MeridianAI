"""Схемы API авторитетного источника транскрипта (Этап 9.8)."""

from typing import Any

from pydantic import BaseModel


class CutoverRolloutOut(BaseModel):
    allowed: bool
    reason: str
    bucket: int


class TranscriptionAuthorityStateOut(BaseModel):
    meeting_id: int
    current_source: str
    revision: int
    fallback_used: bool
    epochs_count: int
    can_promote: bool
    rollout: CutoverRolloutOut
    quality: dict[str, Any] | None = None
    last_switch: dict[str, Any] | None = None


class PromoteRequest(BaseModel):
    reason: str | None = None
    force: bool = False


class FallbackRequest(BaseModel):
    reason: str | None = None


class AuthoritativeSegmentOut(BaseModel):
    segment_key: str
    source: str
    side: str | None = None
    speaker: str | None = None
    text: str
    start_ms: int
    end_ms: int


class AuthoritativeTranscriptOut(BaseModel):
    meeting_id: int
    available: bool          # есть ли эпохи (иначе single-only — постхок не строим)
    epochs_count: int
    sources_used: list[str]
    segment_count: int
    truncated: bool
    segments: list[AuthoritativeSegmentOut]
