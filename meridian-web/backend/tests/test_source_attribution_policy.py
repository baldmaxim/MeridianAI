"""Source Reconciliation policy (Этап 11): resolve config + decision."""

from types import SimpleNamespace

from app.core.context.source_attribution_reconciler import SourceAttributionMatch
from app.core.context.source_attribution_policy import (
    SourceReconcileRuntimeConfig,
    evaluate_source_reconcile_decision,
    resolve_source_reconcile_runtime_config,
)


class _G:
    ai_source_reconcile_enabled = True
    ai_source_reconcile_shadow_mode = True
    ai_source_reconcile_session_overrides_enabled = True
    ai_source_reconcile_min_candidate_confidence = 0.55
    ai_source_reconcile_min_time_overlap = 0.45
    ai_source_reconcile_min_text_similarity = 0.78
    ai_source_reconcile_min_match_score = 0.62
    ai_source_reconcile_ambiguity_margin = 0.08
    ai_source_reconcile_max_candidates = 500
    ai_source_reconcile_max_age_ms = 120000
    ai_source_reconcile_trace_enabled = True
    ai_source_reconcile_trace_sample_rate = 1.0


def _g(**kw):
    g = _G()
    for k, v in kw.items():
        setattr(g, k, v)
    return g


def _cfg(**kw) -> SourceReconcileRuntimeConfig:
    base = dict(enabled=True, shadow_mode=False, session_overrides_enabled=True,
                min_candidate_confidence=0.55, min_time_overlap=0.45, min_text_similarity=0.78,
                min_match_score=0.62, ambiguity_margin=0.08, max_candidates=500, max_age_ms=120000)
    base.update(kw)
    return SourceReconcileRuntimeConfig(**base)


def _match(matched=True, reason="matched", score=0.9):
    return SourceAttributionMatch(matched=matched, reason=reason, match_score=score)


# --- resolve ---

def test_resolve_global_defaults():
    c = resolve_source_reconcile_runtime_config(_G(), None)
    assert c.enabled is True and c.shadow_mode is True
    assert c.min_match_score == 0.62 and c.max_candidates == 500


def test_resolve_session_overrides_applied():
    c = resolve_source_reconcile_runtime_config(_g(), {"source_reconcile_shadow_mode": False,
                                                       "source_reconcile_min_match_score": 0.9})
    assert c.shadow_mode is False
    assert c.min_match_score == 0.9
    assert c.overrides_applied["source_reconcile_shadow_mode"] is True


def test_resolve_overrides_ignored_when_disabled():
    c = resolve_source_reconcile_runtime_config(
        _g(ai_source_reconcile_session_overrides_enabled=False),
        {"source_reconcile_shadow_mode": False})
    assert c.shadow_mode is True  # global preserved
    assert c.overrides_applied["source_reconcile_shadow_mode"] is False


def test_resolve_none_override_uses_global():
    c = resolve_source_reconcile_runtime_config(_g(), {"source_reconcile_shadow_mode": None})
    assert c.shadow_mode is True


def test_resolve_clamps_thresholds_and_limits():
    c = resolve_source_reconcile_runtime_config(_g(), {
        "source_reconcile_min_match_score": 5.0, "source_reconcile_ambiguity_margin": 9.0,
        "source_reconcile_max_candidates": 999999, "source_reconcile_max_age_ms": 5,
        "source_reconcile_trace_sample_rate": -1.0})
    assert c.min_match_score == 1.0
    assert c.ambiguity_margin == 0.5
    assert c.max_candidates == 5000
    assert c.max_age_ms == 1000
    assert c.trace_sample_rate == 0.0


def test_resolve_object_session_ai():
    c = resolve_source_reconcile_runtime_config(_g(), SimpleNamespace(source_reconcile_enabled=False))
    assert c.enabled is False


# --- evaluate ---

def test_evaluate_matched_shadow_true():
    d = evaluate_source_reconcile_decision(_match(), _cfg(shadow_mode=True))
    assert d.would_attach_without_shadow is True
    assert d.actual_attach is False
    assert d.reason == "shadow_mode"


def test_evaluate_matched_shadow_false():
    d = evaluate_source_reconcile_decision(_match(), _cfg(shadow_mode=False))
    assert d.actual_attach is True
    assert d.reason == "allowed"


def test_evaluate_disabled():
    d = evaluate_source_reconcile_decision(_match(), _cfg(enabled=False))
    assert d.actual_attach is False and d.would_attach_without_shadow is False
    assert d.reason == "disabled"


def test_evaluate_no_match_reason_mapping():
    cases = {
        "no_candidates": "no_candidates", "no_speaker_label": "no_speaker_label",
        "no_text_or_time": "no_text_or_time", "low_overlap": "low_overlap",
        "low_text_similarity": "low_text_similarity", "low_confidence": "low_confidence",
        "ambiguous": "ambiguous", "room_mic_blocked": "room_mic_blocked",
        "already_attributed": "already_attributed",
    }
    for match_reason, decision_reason in cases.items():
        d = evaluate_source_reconcile_decision(
            _match(matched=False, reason=match_reason), _cfg(shadow_mode=False))
        assert d.actual_attach is False
        assert d.reason == decision_reason
