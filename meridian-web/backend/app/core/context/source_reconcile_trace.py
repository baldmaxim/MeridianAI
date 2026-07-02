"""Безопасный калибровочный trace Source Reconciliation (Этап 11).

Логирует одну строку `SOURCE_RECONCILE_TRACE {json}` на попытку reconcile для калибровки порогов.
Никогда не логирует raw text / speaker labels / source ids / channel ids / segment ids / имена —
только счётчики, score'ы, enum-категории (reason/source_kind/...) и пороги.
"""

import json
from typing import Optional

from pydantic import BaseModel


class SourceReconcileTraceEvent(BaseModel):
    check_id: str
    session_id: Optional[str] = None
    meeting_id: Optional[str] = None
    enabled: bool
    shadow_mode: bool
    candidate_count: int
    match_attempt_count: int
    match_count: int
    ambiguous_count: int
    rejected_count: int
    matched: bool
    would_attach_without_shadow: bool
    actual_attach: bool
    decision_reason: str
    match_reason: str
    candidate_source: Optional[str] = None
    source_kind: Optional[str] = None
    attribution_source: Optional[str] = None
    attribution_confidence: float = 0.0
    match_score: float = 0.0
    time_overlap: float = 0.0
    text_similarity: float = 0.0
    source_is_isolated: bool = False
    latency_ms: Optional[int] = None
    overrides_applied: Optional[dict] = None
    thresholds: dict = {}


def _sid(v) -> Optional[str]:
    return None if v is None else str(v)


def build_source_reconcile_trace_event(
    *,
    check_id: str,
    config,
    match,
    decision,
    reconciler_stats=None,
    session_id=None,
    meeting_id=None,
    latency_ms: Optional[int] = None,
) -> SourceReconcileTraceEvent:
    """Собрать SourceReconcileTraceEvent из config/match/decision/stats. Только агрегаты/категории."""
    s = reconciler_stats
    return SourceReconcileTraceEvent(
        check_id=check_id,
        session_id=_sid(session_id),
        meeting_id=_sid(meeting_id),
        enabled=bool(getattr(config, "enabled", False)),
        shadow_mode=bool(getattr(config, "shadow_mode", True)),
        candidate_count=getattr(s, "candidate_count", 0) if s is not None else 0,
        match_attempt_count=getattr(s, "match_attempt_count", 0) if s is not None else 0,
        match_count=getattr(s, "match_count", 0) if s is not None else 0,
        ambiguous_count=getattr(s, "ambiguous_count", 0) if s is not None else 0,
        rejected_count=getattr(s, "rejected_count", 0) if s is not None else 0,
        matched=bool(match.matched),
        would_attach_without_shadow=bool(decision.would_attach_without_shadow),
        actual_attach=bool(decision.actual_attach),
        decision_reason=decision.reason,
        match_reason=match.reason,
        candidate_source=match.candidate_source,
        source_kind=match.source_kind,
        attribution_source=match.attribution_source,
        attribution_confidence=match.attribution_confidence,
        match_score=match.match_score,
        time_overlap=match.time_overlap,
        text_similarity=match.text_similarity,
        source_is_isolated=match.source_is_isolated,
        latency_ms=latency_ms,
        overrides_applied=dict(getattr(config, "overrides_applied", {}) or {}) or None,
        thresholds=dict(decision.threshold_summary or {}),
    )


def log_source_reconcile_trace(logger, event: SourceReconcileTraceEvent) -> None:
    """Записать строку SOURCE_RECONCILE_TRACE {json}. Без raw text/labels/source ids/segment ids."""
    payload = json.dumps(event.model_dump(), ensure_ascii=False, sort_keys=True, default=str)
    logger.info("SOURCE_RECONCILE_TRACE %s", payload)
