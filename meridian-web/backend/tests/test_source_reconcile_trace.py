"""Source Reconcile trace (Этап 11): безопасный SOURCE_RECONCILE_TRACE без raw."""

import json

from app.core.context.source_attribution_policy import (
    SourceReconcileRuntimeConfig, evaluate_source_reconcile_decision,
)
from app.core.context.source_attribution_reconciler import SourceAttributionReconciler
from app.core.context.source_reconcile_trace import (
    build_source_reconcile_trace_event, log_source_reconcile_trace,
)


class _CapLogger:
    def __init__(self):
        self.lines = []

    def info(self, msg, *args):
        self.lines.append(msg % args if args else msg)


def _cfg(shadow=False):
    return SourceReconcileRuntimeConfig(
        enabled=True, shadow_mode=shadow, session_overrides_enabled=True,
        min_candidate_confidence=0.55, min_time_overlap=0.45, min_text_similarity=0.78,
        min_match_score=0.62, ambiguity_margin=0.08, max_candidates=500, max_age_ms=120000)


def _matched_event(shadow=False):
    r = SourceAttributionReconciler()
    r.observe_candidate({"text": "дайте лучше условия", "start_ms": 1000, "end_ms": 3000,
                         "audio_source_id": "secondary", "source_is_isolated": True,
                         "source_kind": "multi_channel", "attribution_source": "multi_source_segment",
                         "attribution_confidence": 0.9, "candidate_pipeline": "multi_channel_live",
                         "candidate_id": "c1"})
    cfg = _cfg(shadow)
    match = r.reconcile_segment({"speaker_label": "SM_1", "segment_id": "s1",
                                 "text": "дайте лучше условия", "start_ms": 1100, "end_ms": 2900})
    decision = evaluate_source_reconcile_decision(match, cfg)
    return build_source_reconcile_trace_event(
        check_id="chk09zk", config=cfg, match=match, decision=decision,
        reconciler_stats=r.get_stats(), session_id=7, meeting_id=42, latency_ms=12)


def test_trace_event_no_raw_values():
    ev = _matched_event(shadow=False)
    payload = json.dumps(ev.model_dump(), ensure_ascii=False)
    for leak in ("SM_1", "secondary", "дайте", "s1", "c1", "Channel"):
        assert leak not in payload
    # категории/решение присутствуют
    assert ev.candidate_source == "multi_channel_live"
    assert ev.source_kind == "multi_channel"
    assert ev.actual_attach is True
    assert ev.would_attach_without_shadow is True


def test_trace_shadow_would_but_not_actual():
    ev = _matched_event(shadow=True)
    assert ev.would_attach_without_shadow is True
    assert ev.actual_attach is False
    assert ev.decision_reason == "shadow_mode"


def test_log_line_marker_and_no_raw():
    ev = _matched_event(shadow=False)
    log = _CapLogger()
    log_source_reconcile_trace(log, ev)
    assert len(log.lines) == 1
    line = log.lines[0]
    assert line.startswith("SOURCE_RECONCILE_TRACE {")
    for leak in ("SM_1", "secondary", "дайте", "s1", "c1"):
        assert leak not in line
    parsed = json.loads(line[len("SOURCE_RECONCILE_TRACE "):])
    assert parsed["check_id"] == "chk09zk"
    assert "thresholds" in parsed
    assert "transcript" not in parsed and "raw_response" not in parsed
