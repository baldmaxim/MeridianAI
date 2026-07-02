"""Safe per-channel STT canary trace (Этап 17).

Логирует одну строку `PER_CHANNEL_STT_TRACE {json}` с агрегатами per-channel STT pipeline. НИКОГДА
не логирует raw text / raw audio / source ids / channel labels / speaker labels / device ids — только
счётчики, средние и enum last_error_kind.
"""

import json
from typing import Optional

from pydantic import BaseModel


class PerChannelSttTraceEvent(BaseModel):
    check_id: str
    session_id: Optional[str] = None
    meeting_id: Optional[str] = None
    enabled: bool
    shadow_mode: bool
    frame_count: int
    segment_started_count: int
    segment_finalized_count: int
    segment_dropped_low_rms_count: int
    segment_dropped_low_dominance_count: int
    segment_dropped_rate_limit_count: int
    transcribe_attempt_count: int
    transcribe_success_count: int
    transcribe_error_count: int
    candidate_emit_count: int
    candidate_shadow_suppressed_count: int
    max_channels_seen: int
    active_channel_count: int
    average_dominance: Optional[float] = None
    average_transcribe_latency_ms: Optional[float] = None
    last_error_kind: Optional[str] = None
    # Provider adapter (Этап 18) — без raw text/audio/source ids
    provider: Optional[str] = None
    transcribe_timeout_count: int = 0
    transcribe_empty_text_count: int = 0
    transcribe_provider_error_count: int = 0
    transcribe_budget_exhausted_count: int = 0
    transcribe_cache_hit_count: int = 0
    transcribe_cache_miss_count: int = 0
    transcribe_audio_too_long_count: int = 0
    transcribe_audio_too_large_count: int = 0
    adapter_unavailable_count: int = 0
    # Budget/cost (Этап 20)
    provider_calls_used: int = 0
    provider_audio_seconds_used: float = 0.0
    overrides_applied: Optional[dict] = None


def _sid(v) -> Optional[str]:
    return None if v is None else str(v)


def build_per_channel_stt_trace_event(
    *,
    check_id: str,
    stats,
    config=None,
    session_id=None,
    meeting_id=None,
) -> PerChannelSttTraceEvent:
    """Собрать trace-событие из PerChannelSttStats (+опц. config.overrides_applied)."""
    overrides = None
    if config is not None:
        ov = getattr(config, "overrides_applied", None)
        overrides = dict(ov) if ov else None
    return PerChannelSttTraceEvent(
        check_id=check_id,
        session_id=_sid(session_id),
        meeting_id=_sid(meeting_id),
        enabled=bool(getattr(stats, "enabled", False)),
        shadow_mode=bool(getattr(stats, "shadow_mode", True)),
        frame_count=getattr(stats, "frame_count", 0),
        segment_started_count=getattr(stats, "segment_started_count", 0),
        segment_finalized_count=getattr(stats, "segment_finalized_count", 0),
        segment_dropped_low_rms_count=getattr(stats, "segment_dropped_low_rms_count", 0),
        segment_dropped_low_dominance_count=getattr(stats, "segment_dropped_low_dominance_count", 0),
        segment_dropped_rate_limit_count=getattr(stats, "segment_dropped_rate_limit_count", 0),
        transcribe_attempt_count=getattr(stats, "transcribe_attempt_count", 0),
        transcribe_success_count=getattr(stats, "transcribe_success_count", 0),
        transcribe_error_count=getattr(stats, "transcribe_error_count", 0),
        candidate_emit_count=getattr(stats, "candidate_emit_count", 0),
        candidate_shadow_suppressed_count=getattr(stats, "candidate_shadow_suppressed_count", 0),
        max_channels_seen=getattr(stats, "max_channels_seen", 0),
        active_channel_count=getattr(stats, "active_channel_count", 0),
        average_dominance=getattr(stats, "average_dominance", None),
        average_transcribe_latency_ms=getattr(stats, "average_transcribe_latency_ms", None),
        last_error_kind=getattr(stats, "last_error_kind", None),
        provider=getattr(stats, "provider", None),
        transcribe_timeout_count=getattr(stats, "transcribe_timeout_count", 0),
        transcribe_empty_text_count=getattr(stats, "transcribe_empty_text_count", 0),
        transcribe_provider_error_count=getattr(stats, "transcribe_provider_error_count", 0),
        transcribe_budget_exhausted_count=getattr(stats, "transcribe_budget_exhausted_count", 0),
        transcribe_cache_hit_count=getattr(stats, "transcribe_cache_hit_count", 0),
        transcribe_cache_miss_count=getattr(stats, "transcribe_cache_miss_count", 0),
        transcribe_audio_too_long_count=getattr(stats, "transcribe_audio_too_long_count", 0),
        transcribe_audio_too_large_count=getattr(stats, "transcribe_audio_too_large_count", 0),
        adapter_unavailable_count=getattr(stats, "adapter_unavailable_count", 0),
        provider_calls_used=getattr(stats, "provider_calls_used", 0),
        provider_audio_seconds_used=getattr(stats, "provider_audio_seconds_used", 0.0),
        overrides_applied=overrides,
    )


def log_per_channel_stt_trace(logger, event: PerChannelSttTraceEvent) -> None:
    """Записать строку PER_CHANNEL_STT_TRACE {json}. Без raw text/audio/source ids/labels."""
    payload = json.dumps(event.model_dump(), ensure_ascii=False, sort_keys=True, default=str)
    logger.info("PER_CHANNEL_STT_TRACE %s", payload)
