"""Безопасный structured trace для Signal Engine (Этап 2).

Логирует одну строку `SIGNAL_ENGINE_TRACE {json}` для калибровки. По умолчанию НЕ
включает фрагменты переговоров — только длины, hash и агрегированные поля. При
TRACE_INCLUDE_TEXT=true добавляет ТОЛЬКО safe_preview (маскированный, обрезанный).
Никогда не логирует raw_response LLM и полный transcript/document_context.
"""

import hashlib
import json
import re
from typing import Optional

from pydantic import BaseModel

from .signal_engine import SignalEngineResult
from .signal_policy import SignalDecision

# Грубая маскировка PII в preview
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")


class SignalTraceEvent(BaseModel):
    check_id: str
    session_id: Optional[str] = None
    meeting_id: Optional[str] = None
    source_method: Optional[str] = None
    shadow_mode: bool
    situation_type: str
    phase: str
    speaker_side: str
    risk_level: str
    should_prompt: bool
    confidence: float
    urgency: float
    actionability: float
    novelty_key: str
    recommended_card_types: list[str]
    error_kind: str
    used_fallback: bool
    decision_reason: str
    actual_should_prompt: bool
    would_prompt_without_shadow: bool
    legacy_fallback_allowed: bool
    cooldown_key: Optional[str] = None
    score: float
    latency_ms: Optional[int] = None
    recent_dialog_chars: int
    current_text_chars: int
    document_context_chars: int
    text_hash: Optional[str] = None
    current_text_preview: Optional[str] = None
    recent_dialog_preview: Optional[str] = None
    # Speaker Identity Graph — ТОЛЬКО агрегаты (без имён/меток/сырого текста ролей).
    speaker_context_chars: int = 0
    speaker_side_counts: Optional[dict] = None
    speaker_average_confidence: Optional[float] = None
    speaker_sources: Optional[dict] = None
    speaker_count: Optional[int] = None
    speaker_unknown_side_count: Optional[int] = None
    speaker_hint_source_count: Optional[int] = None
    # Audio/channel link агрегаты (Этап 6) — без raw labels/source ids/route.
    speaker_audio_linked_count: Optional[int] = None
    speaker_channel_linked_count: Optional[int] = None
    speaker_audio_link_average_confidence: Optional[float] = None
    speaker_audio_link_sources: Optional[dict] = None
    # Live attribution агрегаты (Этап 7) — только счётчики/агрегаты, без raw labels/source ids.
    speaker_audio_attribution_observation_count: Optional[int] = None
    speaker_audio_attribution_stable_link_count: Optional[int] = None
    speaker_audio_attribution_ambiguous_count: Optional[int] = None
    speaker_audio_attribution_average_confidence: Optional[float] = None
    speaker_audio_attribution_sources: Optional[dict] = None
    # Source reconciliation агрегаты (Этап 10) — без raw text/source ids/channel ids/labels.
    source_reconcile_candidate_count: Optional[int] = None
    source_reconcile_match_attempt_count: Optional[int] = None
    source_reconcile_match_count: Optional[int] = None
    source_reconcile_ambiguous_count: Optional[int] = None
    source_reconcile_rejected_count: Optional[int] = None
    source_reconcile_average_match_score: Optional[float] = None
    source_reconcile_candidate_sources: Optional[dict] = None
    source_reconcile_match_reasons: Optional[dict] = None
    # Source reconcile shadow/decision (Этап 11) — детали в отдельном SOURCE_RECONCILE_TRACE.
    source_reconcile_shadow_mode: Optional[bool] = None
    source_reconcile_would_attach_count: Optional[int] = None
    source_reconcile_actual_attach_count: Optional[int] = None
    source_reconcile_decision_reasons: Optional[dict] = None
    # Audio capture route (Этап 15) — техническая зона записи, НЕ сторона. Без raw device label/id.
    audio_capture_route: Optional[str] = None
    audio_capture_pipeline: Optional[str] = None
    audio_capture_actual_channel_count: Optional[int] = None
    audio_capture_actual_sample_rate: Optional[int] = None
    audio_capture_source_kind: Optional[str] = None
    audio_capture_source_is_isolated: Optional[bool] = None
    # Multichannel v2 shadow (Этап 16) — только безопасные агрегаты, без raw audio/source ids/labels.
    audio_multichannel_shadow_enabled: Optional[bool] = None
    audio_multichannel_frame_count: Optional[int] = None
    audio_multichannel_parse_error_count: Optional[int] = None
    audio_multichannel_sequence_gap_count: Optional[int] = None
    audio_multichannel_max_channels_seen: Optional[int] = None
    audio_multichannel_last_channels: Optional[int] = None
    audio_multichannel_last_sample_rate: Optional[int] = None
    audio_multichannel_clipping_event_count: Optional[int] = None
    # Per-channel STT canary (Этап 17) — только безопасные агрегаты, без raw text/audio/source ids.
    audio_per_channel_stt_enabled: Optional[bool] = None
    audio_per_channel_stt_shadow_mode: Optional[bool] = None
    audio_per_channel_stt_segment_finalized_count: Optional[int] = None
    audio_per_channel_stt_transcribe_success_count: Optional[int] = None
    audio_per_channel_stt_transcribe_error_count: Optional[int] = None
    audio_per_channel_stt_candidate_emit_count: Optional[int] = None
    audio_per_channel_stt_candidate_shadow_suppressed_count: Optional[int] = None
    audio_per_channel_stt_average_dominance: Optional[float] = None
    # Provider adapter subset (Этап 18) — без raw text/audio/provider response
    audio_per_channel_stt_provider: Optional[str] = None
    audio_per_channel_stt_adapter_unavailable_count: Optional[int] = None
    audio_per_channel_stt_cache_hit_count: Optional[int] = None
    audio_per_channel_stt_budget_exhausted_count: Optional[int] = None
    audio_per_channel_stt_timeout_count: Optional[int] = None
    # Budget/cost subset (Этап 20)
    audio_per_channel_stt_provider_calls_used: Optional[int] = None
    audio_per_channel_stt_provider_audio_seconds_used: Optional[float] = None


def make_text_hash(text: str) -> str:
    """Стабильный короткий sha256-хэш текста (не раскрывает содержимое)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def safe_preview(text: str, max_chars: int = 300) -> str:
    """Безопасный preview: схлопнуть пробелы, замаскировать email/телефоны, обрезать."""
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    t = _EMAIL_RE.sub("[email]", t)
    t = _PHONE_RE.sub("[phone]", t)
    if len(t) > max_chars:
        t = t[:max_chars]
    return t


def _sid(v) -> Optional[str]:
    return None if v is None else str(v)


_EMPTY_SPEAKER_STATS = {
    "speaker_side_counts": None, "speaker_average_confidence": None, "speaker_sources": None,
    "speaker_count": None, "unknown_side_count": None, "hint_source_count": None,
}


def _speaker_aggregates(speaker_map, speaker_stats) -> dict:
    """Только безопасные агрегаты по спикерам. Имена/метки НЕ извлекаются.

    Принимает SpeakerIdentityMap (через speaker_identity_stats) или готовый dict speaker_stats.
    """
    from .speaker_identity import speaker_identity_stats
    if speaker_map is not None:
        stats = speaker_identity_stats(speaker_map)
        return stats if stats.get("speaker_count") else dict(_EMPTY_SPEAKER_STATS)
    if isinstance(speaker_stats, dict) and speaker_stats:
        return {
            "speaker_side_counts": speaker_stats.get("speaker_side_counts") or speaker_stats.get("side_counts"),
            "speaker_average_confidence": speaker_stats.get("speaker_average_confidence")
            or speaker_stats.get("average_confidence"),
            "speaker_sources": speaker_stats.get("speaker_sources") or speaker_stats.get("source_summary"),
            "speaker_count": speaker_stats.get("speaker_count"),
            "unknown_side_count": speaker_stats.get("unknown_side_count"),
            "hint_source_count": speaker_stats.get("hint_source_count"),
        }
    return dict(_EMPTY_SPEAKER_STATS)


_EMPTY_AUDIO_LINK = {
    "audio_linked_count": None, "channel_linked_count": None,
    "average_confidence": None, "source_summary": None,
}


def _audio_link_aggregates(audio_link_map, audio_link_stats) -> dict:
    """Только безопасные агрегаты по audio/channel-линкам (без labels/source ids/route)."""
    if audio_link_map is not None:
        if not getattr(audio_link_map, "linked_speaker_count", 0):
            return dict(_EMPTY_AUDIO_LINK)
        return {
            "audio_linked_count": getattr(audio_link_map, "audio_source_count", 0),
            "channel_linked_count": getattr(audio_link_map, "channel_label_count", 0),
            "average_confidence": getattr(audio_link_map, "average_confidence", 0.0),
            "source_summary": dict(getattr(audio_link_map, "source_summary", {}) or {}),
        }
    if isinstance(audio_link_stats, dict) and audio_link_stats:
        return {
            "audio_linked_count": audio_link_stats.get("audio_linked_count")
            or audio_link_stats.get("audio_linked_speaker_count"),
            "channel_linked_count": audio_link_stats.get("channel_linked_count")
            or audio_link_stats.get("channel_linked_speaker_count"),
            "average_confidence": audio_link_stats.get("average_confidence")
            or audio_link_stats.get("audio_link_average_confidence"),
            "source_summary": audio_link_stats.get("source_summary")
            or audio_link_stats.get("audio_link_source_summary"),
        }
    return dict(_EMPTY_AUDIO_LINK)


_EMPTY_ATTRIBUTION = {
    "observation_count": None, "stable_link_count": None, "ambiguous_count": None,
    "average_confidence": None, "sources": None,
}


def _attribution_aggregates(attribution_stats) -> dict:
    """Только безопасные агрегаты live-attribution (без raw labels/source ids)."""
    if attribution_stats is None:
        return dict(_EMPTY_ATTRIBUTION)
    s = attribution_stats
    if isinstance(s, dict):
        obs = s.get("observation_count")
        return {
            "observation_count": obs,
            "stable_link_count": s.get("stable_link_count"),
            "ambiguous_count": s.get("ambiguous_speaker_count"),
            "average_confidence": s.get("average_link_confidence"),
            "sources": dict(s.get("by_observation_source") or {}) or None,
        }
    # SpeakerAudioAttributionStats-подобный объект
    obs = getattr(s, "observation_count", 0)
    if not obs:
        return dict(_EMPTY_ATTRIBUTION)
    return {
        "observation_count": obs,
        "stable_link_count": getattr(s, "stable_link_count", 0),
        "ambiguous_count": getattr(s, "ambiguous_speaker_count", 0),
        "average_confidence": getattr(s, "average_link_confidence", 0.0),
        "sources": dict(getattr(s, "by_observation_source", {}) or {}) or None,
    }


_EMPTY_RECONCILE = {
    "candidate_count": None, "match_attempt_count": None, "match_count": None,
    "ambiguous_count": None, "rejected_count": None, "average_match_score": None,
    "candidate_sources": None, "match_reasons": None,
}


def _reconcile_aggregates(stats) -> dict:
    """Только безопасные агрегаты source reconciliation (без raw text/source ids/labels)."""
    if stats is None:
        return dict(_EMPTY_RECONCILE)
    s = stats
    if isinstance(s, dict):
        attempts = s.get("match_attempt_count")
        if not (s.get("candidate_count") or attempts):
            return dict(_EMPTY_RECONCILE)
        return {
            "candidate_count": s.get("candidate_count"),
            "match_attempt_count": attempts,
            "match_count": s.get("match_count"),
            "ambiguous_count": s.get("ambiguous_count"),
            "rejected_count": s.get("rejected_count"),
            "average_match_score": s.get("average_match_score"),
            "candidate_sources": dict(s.get("by_candidate_source") or {}) or None,
            "match_reasons": dict(s.get("by_match_reason") or {}) or None,
        }
    attempts = getattr(s, "match_attempt_count", 0)
    if not (getattr(s, "candidate_count", 0) or attempts):
        return dict(_EMPTY_RECONCILE)
    return {
        "candidate_count": getattr(s, "candidate_count", 0),
        "match_attempt_count": attempts,
        "match_count": getattr(s, "match_count", 0),
        "ambiguous_count": getattr(s, "ambiguous_count", 0),
        "rejected_count": getattr(s, "rejected_count", 0),
        "average_match_score": getattr(s, "average_match_score", 0.0),
        "candidate_sources": dict(getattr(s, "by_candidate_source", {}) or {}) or None,
        "match_reasons": dict(getattr(s, "by_match_reason", {}) or {}) or None,
    }


def _audio_capture_aggregates(meta) -> dict:
    """Безопасные поля audio capture route из AudioCaptureMetadata (без device label/id).

    Только техническая зона записи (route/pipeline/каналы/sample rate/source_kind) — НЕ сторона.
    """
    if meta is None:
        return {"route": None, "pipeline": None, "actual_channel_count": None,
                "actual_sample_rate": None, "source_kind": None, "source_is_isolated": None}
    return {
        "route": getattr(meta, "route", None),
        "pipeline": getattr(meta, "capture_pipeline", None),
        "actual_channel_count": getattr(meta, "actual_channel_count", None),
        "actual_sample_rate": getattr(meta, "actual_sample_rate", None),
        "source_kind": getattr(meta, "source_kind", None),
        "source_is_isolated": getattr(meta, "source_is_isolated", None),
    }


def _multichannel_shadow_aggregates(stats) -> dict:
    """Безопасные агрегаты v2 shadow ingest (без raw audio/source ids/channel labels)."""
    if stats is None:
        return {k: None for k in (
            "enabled", "frame_count", "parse_error_count", "sequence_gap_count",
            "max_channels_seen", "last_channels", "last_sample_rate", "clipping_event_count")}
    return {
        "enabled": getattr(stats, "enabled", None),
        "frame_count": getattr(stats, "frame_count", None),
        "parse_error_count": getattr(stats, "parse_error_count", None),
        "sequence_gap_count": getattr(stats, "sequence_gap_count", None),
        "max_channels_seen": getattr(stats, "max_channels_seen", None),
        "last_channels": getattr(stats, "last_channels", None),
        "last_sample_rate": getattr(stats, "last_sample_rate", None),
        "clipping_event_count": getattr(stats, "clipping_event_count", None),
    }


def _per_channel_stt_aggregates(stats) -> dict:
    """Безопасные агрегаты per-channel STT (без raw text/audio/source ids/channel labels)."""
    keys = ("enabled", "shadow_mode", "segment_finalized_count", "transcribe_success_count",
            "transcribe_error_count", "candidate_emit_count", "candidate_shadow_suppressed_count",
            "average_dominance",
            # provider subset (Этап 18)
            "provider", "adapter_unavailable_count", "transcribe_cache_hit_count",
            "transcribe_budget_exhausted_count", "transcribe_timeout_count",
            # budget/cost subset (Этап 20)
            "provider_calls_used", "provider_audio_seconds_used")
    if stats is None:
        return {k: None for k in keys}
    return {k: getattr(stats, k, None) for k in keys}


def build_signal_trace_event(
    *,
    check_id: str,
    result: SignalEngineResult,
    decision: SignalDecision,
    shadow_mode: bool,
    signal=None,
    recent_dialog: str = "",
    current_text: str = "",
    document_context: str = "",
    session_id=None,
    meeting_id=None,
    source_method: Optional[str] = None,
    latency_ms: Optional[int] = None,
    include_text: bool = False,
    preview_max_chars: int = 300,
    speaker_context: str = "",
    speaker_map=None,
    speaker_stats: Optional[dict] = None,
    audio_link_map=None,
    audio_link_stats: Optional[dict] = None,
    attribution_stats=None,
    source_reconcile_stats=None,
    source_reconcile_decision_stats: Optional[dict] = None,
    audio_capture_metadata=None,
    multichannel_shadow_stats=None,
    per_channel_stt_stats=None,
) -> SignalTraceEvent:
    """Собрать SignalTraceEvent. По умолчанию без preview текста переговоров.

    speaker_map (SpeakerIdentityMap) / speaker_stats — источник АГРЕГАТОВ по спикерам.
    В trace попадают только side_counts/source_summary/average_confidence — НЕ имена/метки.
    """
    sig = signal if signal is not None else result.signal
    sp = _speaker_aggregates(speaker_map, speaker_stats)
    al = _audio_link_aggregates(audio_link_map, audio_link_stats)
    at = _attribution_aggregates(attribution_stats)
    rc = _reconcile_aggregates(source_reconcile_stats)
    rds = source_reconcile_decision_stats or {}
    ac = _audio_capture_aggregates(audio_capture_metadata)
    mc = _multichannel_shadow_aggregates(multichannel_shadow_stats)
    pcs = _per_channel_stt_aggregates(per_channel_stt_stats)
    event = SignalTraceEvent(
        check_id=check_id,
        session_id=_sid(session_id),
        meeting_id=_sid(meeting_id),
        source_method=source_method,
        shadow_mode=shadow_mode,
        situation_type=sig.situation_type,
        phase=sig.phase,
        speaker_side=sig.speaker_side,
        risk_level=sig.risk_level,
        should_prompt=sig.should_prompt,
        confidence=sig.confidence,
        urgency=sig.urgency,
        actionability=sig.actionability,
        novelty_key=sig.novelty_key,
        recommended_card_types=list(sig.recommended_card_types),
        error_kind=result.error_kind,
        used_fallback=result.used_fallback,
        decision_reason=decision.reason,
        actual_should_prompt=decision.actual_should_prompt,
        would_prompt_without_shadow=decision.would_prompt_without_shadow,
        legacy_fallback_allowed=decision.legacy_fallback_allowed,
        cooldown_key=decision.cooldown_key,
        score=decision.score,
        latency_ms=latency_ms,
        recent_dialog_chars=len(recent_dialog or ""),
        current_text_chars=len(current_text or ""),
        document_context_chars=len(document_context or ""),
        text_hash=make_text_hash(current_text or ""),
        speaker_context_chars=len(speaker_context or ""),
        speaker_side_counts=sp["speaker_side_counts"],
        speaker_average_confidence=sp["speaker_average_confidence"],
        speaker_sources=sp["speaker_sources"],
        speaker_count=sp["speaker_count"],
        speaker_unknown_side_count=sp["unknown_side_count"],
        speaker_hint_source_count=sp["hint_source_count"],
        speaker_audio_linked_count=al["audio_linked_count"],
        speaker_channel_linked_count=al["channel_linked_count"],
        speaker_audio_link_average_confidence=al["average_confidence"],
        speaker_audio_link_sources=al["source_summary"],
        speaker_audio_attribution_observation_count=at["observation_count"],
        speaker_audio_attribution_stable_link_count=at["stable_link_count"],
        speaker_audio_attribution_ambiguous_count=at["ambiguous_count"],
        speaker_audio_attribution_average_confidence=at["average_confidence"],
        speaker_audio_attribution_sources=at["sources"],
        source_reconcile_candidate_count=rc["candidate_count"],
        source_reconcile_match_attempt_count=rc["match_attempt_count"],
        source_reconcile_match_count=rc["match_count"],
        source_reconcile_ambiguous_count=rc["ambiguous_count"],
        source_reconcile_rejected_count=rc["rejected_count"],
        source_reconcile_average_match_score=rc["average_match_score"],
        source_reconcile_candidate_sources=rc["candidate_sources"],
        source_reconcile_match_reasons=rc["match_reasons"],
        source_reconcile_shadow_mode=rds.get("shadow_mode"),
        source_reconcile_would_attach_count=rds.get("would_attach_count"),
        source_reconcile_actual_attach_count=rds.get("actual_attach_count"),
        source_reconcile_decision_reasons=(dict(rds.get("decision_reasons") or {}) or None),
        audio_capture_route=ac["route"],
        audio_capture_pipeline=ac["pipeline"],
        audio_capture_actual_channel_count=ac["actual_channel_count"],
        audio_capture_actual_sample_rate=ac["actual_sample_rate"],
        audio_capture_source_kind=ac["source_kind"],
        audio_capture_source_is_isolated=ac["source_is_isolated"],
        audio_multichannel_shadow_enabled=mc["enabled"],
        audio_multichannel_frame_count=mc["frame_count"],
        audio_multichannel_parse_error_count=mc["parse_error_count"],
        audio_multichannel_sequence_gap_count=mc["sequence_gap_count"],
        audio_multichannel_max_channels_seen=mc["max_channels_seen"],
        audio_multichannel_last_channels=mc["last_channels"],
        audio_multichannel_last_sample_rate=mc["last_sample_rate"],
        audio_multichannel_clipping_event_count=mc["clipping_event_count"],
        audio_per_channel_stt_enabled=pcs["enabled"],
        audio_per_channel_stt_shadow_mode=pcs["shadow_mode"],
        audio_per_channel_stt_segment_finalized_count=pcs["segment_finalized_count"],
        audio_per_channel_stt_transcribe_success_count=pcs["transcribe_success_count"],
        audio_per_channel_stt_transcribe_error_count=pcs["transcribe_error_count"],
        audio_per_channel_stt_candidate_emit_count=pcs["candidate_emit_count"],
        audio_per_channel_stt_candidate_shadow_suppressed_count=pcs["candidate_shadow_suppressed_count"],
        audio_per_channel_stt_average_dominance=pcs["average_dominance"],
        audio_per_channel_stt_provider=pcs["provider"],
        audio_per_channel_stt_adapter_unavailable_count=pcs["adapter_unavailable_count"],
        audio_per_channel_stt_cache_hit_count=pcs["transcribe_cache_hit_count"],
        audio_per_channel_stt_budget_exhausted_count=pcs["transcribe_budget_exhausted_count"],
        audio_per_channel_stt_timeout_count=pcs["transcribe_timeout_count"],
        audio_per_channel_stt_provider_calls_used=pcs["provider_calls_used"],
        audio_per_channel_stt_provider_audio_seconds_used=pcs["provider_audio_seconds_used"],
    )
    if include_text:
        # Только safe_preview, и только для реплик (НЕ для document_context).
        event.current_text_preview = safe_preview(current_text, preview_max_chars)
        event.recent_dialog_preview = safe_preview(recent_dialog, preview_max_chars)
    return event


def log_signal_trace(logger, event: SignalTraceEvent) -> None:
    """Записать одну строку SIGNAL_ENGINE_TRACE {json}. Без raw_response/полных текстов."""
    payload = json.dumps(
        event.model_dump(), ensure_ascii=False, sort_keys=True, default=str
    )
    logger.info("SIGNAL_ENGINE_TRACE %s", payload)
