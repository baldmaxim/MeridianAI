"""Source Attribution Reconciliation policy (Этап 11): runtime config + decision.

Выносит из SessionManager resolve конфигурации (global + per-meeting canary override) и
решение attach/shadow в чистые тестируемые функции. Никаких побочных эффектов и LLM.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel

from .source_attribution_reconciler import SourceAttributionMatch

_MISSING = object()


class SourceReconcileRuntimeConfig(BaseModel):
    enabled: bool
    shadow_mode: bool
    session_overrides_enabled: bool
    min_candidate_confidence: float
    min_time_overlap: float
    min_text_similarity: float
    min_match_score: float
    ambiguity_margin: float
    max_candidates: int
    max_age_ms: int
    trace_enabled: bool = True
    trace_sample_rate: float = 1.0
    overrides_applied: dict = {}


class SourceReconcileDecision(BaseModel):
    actual_attach: bool
    would_attach_without_shadow: bool
    reason: Literal[
        "disabled", "shadow_mode", "allowed", "no_match", "already_attributed",
        "candidate_rejected", "low_confidence", "low_overlap", "low_text_similarity",
        "low_match_score", "ambiguous", "room_mic_blocked", "no_candidates",
        "no_speaker_label", "no_text_or_time",
    ]
    match_reason: str
    score: float = 0.0
    time_overlap: float = 0.0
    text_similarity: float = 0.0
    attribution_confidence: float = 0.0
    threshold_summary: dict = {}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _session_get(session_ai: Any, key: str):
    if session_ai is None:
        return _MISSING
    val = session_ai.get(key, _MISSING) if isinstance(session_ai, dict) else getattr(session_ai, key, _MISSING)
    return _MISSING if val is None else val


# match.reason → decision.reason (для НЕ-matched)
_MATCH_REASON_MAP = {
    "no_candidates": "no_candidates",
    "no_speaker_label": "no_speaker_label",
    "no_text_or_time": "no_text_or_time",
    "low_overlap": "low_overlap",
    "low_text_similarity": "low_text_similarity",
    "low_confidence": "low_confidence",
    "ambiguous": "ambiguous",
    "room_mic_blocked": "room_mic_blocked",
    "already_attributed": "already_attributed",
}


def resolve_source_reconcile_runtime_config(global_settings, session_ai: Any = None) -> SourceReconcileRuntimeConfig:
    """Собрать runtime config из global config + опц. per-meeting canary override.

    session_ai (dict/object) ключи source_reconcile_* перекрывают global, ТОЛЬКО если
    session_overrides_enabled. None = «использовать global». Все пороги/ставки clamp."""
    g = global_settings
    overrides_enabled = bool(getattr(g, "ai_source_reconcile_session_overrides_enabled", True))
    applied: dict = {}

    def pick(key: str, default):
        if not overrides_enabled:
            applied[key] = False
            return default
        val = _session_get(session_ai, key)
        if val is _MISSING:
            applied[key] = False
            return default
        applied[key] = True
        return val

    enabled = pick("source_reconcile_enabled", g.ai_source_reconcile_enabled)
    shadow = pick("source_reconcile_shadow_mode", g.ai_source_reconcile_shadow_mode)
    min_conf = pick("source_reconcile_min_candidate_confidence", g.ai_source_reconcile_min_candidate_confidence)
    min_to = pick("source_reconcile_min_time_overlap", g.ai_source_reconcile_min_time_overlap)
    min_ts = pick("source_reconcile_min_text_similarity", g.ai_source_reconcile_min_text_similarity)
    min_score = pick("source_reconcile_min_match_score", g.ai_source_reconcile_min_match_score)
    margin = pick("source_reconcile_ambiguity_margin", g.ai_source_reconcile_ambiguity_margin)
    max_cand = pick("source_reconcile_max_candidates", g.ai_source_reconcile_max_candidates)
    max_age = pick("source_reconcile_max_age_ms", g.ai_source_reconcile_max_age_ms)
    trace_enabled = pick("source_reconcile_trace_enabled", g.ai_source_reconcile_trace_enabled)
    sample_rate = pick("source_reconcile_trace_sample_rate", g.ai_source_reconcile_trace_sample_rate)

    return SourceReconcileRuntimeConfig(
        enabled=bool(enabled),
        shadow_mode=bool(shadow),
        session_overrides_enabled=overrides_enabled,
        min_candidate_confidence=_clamp(_as_float(min_conf, 0.55), 0.0, 1.0),
        min_time_overlap=_clamp(_as_float(min_to, 0.45), 0.0, 1.0),
        min_text_similarity=_clamp(_as_float(min_ts, 0.78), 0.0, 1.0),
        min_match_score=_clamp(_as_float(min_score, 0.62), 0.0, 1.0),
        ambiguity_margin=_clamp(_as_float(margin, 0.08), 0.0, 0.5),
        max_candidates=int(_clamp(_as_int(max_cand, 500), 10, 5000)),
        max_age_ms=int(_clamp(_as_int(max_age, 120000), 1000, 600000)),
        trace_enabled=bool(trace_enabled),
        trace_sample_rate=_clamp(_as_float(sample_rate, 1.0), 0.0, 1.0),
        overrides_applied=applied,
    )


def evaluate_source_reconcile_decision(
    match: SourceAttributionMatch, config: SourceReconcileRuntimeConfig,
) -> SourceReconcileDecision:
    """Чистое решение attach/shadow по результату reconcile. Не делает attach сам."""
    thr = {
        "min_candidate_confidence": config.min_candidate_confidence,
        "min_time_overlap": config.min_time_overlap,
        "min_text_similarity": config.min_text_similarity,
        "min_match_score": config.min_match_score,
        "ambiguity_margin": config.ambiguity_margin,
    }

    def _d(actual, would, reason):
        return SourceReconcileDecision(
            actual_attach=actual, would_attach_without_shadow=would, reason=reason,
            match_reason=match.reason, score=match.match_score, time_overlap=match.time_overlap,
            text_similarity=match.text_similarity, attribution_confidence=match.attribution_confidence,
            threshold_summary=thr)

    if not config.enabled:
        return _d(False, False, "disabled")
    if not match.matched:
        reason = _MATCH_REASON_MAP.get(match.reason, "no_match")
        return _d(False, False, reason)
    # matched
    if config.shadow_mode:
        return _d(False, True, "shadow_mode")
    return _d(True, True, "allowed")
