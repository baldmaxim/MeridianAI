"""Combined canary readiness analyzer (Этап 12)."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.canary_readiness_analysis import (
    analyze_canary_readiness,
    analyze_canary_readiness_from_events,
    extract_all_canary_trace_events_from_lines,
)


def _sr(**kw) -> dict:
    base = dict(would_attach_without_shadow=True, actual_attach=False, decision_reason="shadow_mode",
                match_reason="matched", match_score=0.9, time_overlap=1.0, text_similarity=1.0,
                attribution_confidence=0.85, candidate_source="multi_channel_live",
                source_kind="multi_channel", attribution_source="multi_source_segment")
    base.update(kw)
    return base


def _se(**kw) -> dict:
    base = dict(situation_type="price_pressure", decision_reason="shadow_mode", error_kind="none",
                would_prompt_without_shadow=True, actual_should_prompt=False, score=0.4, latency_ms=120,
                speaker_side_counts={"unknown": 1}, speaker_unknown_side_count=1, speaker_count=1,
                speaker_context_chars=10, speaker_hint_source_count=0,
                speaker_audio_linked_count=0)
    base.update(kw)
    return base


def _a(sr=None, se=None):
    return analyze_canary_readiness(source_reconcile_events=sr or [], signal_engine_events=se or [])


def test_no_data():
    r = _a()
    assert r["verdict"] == "no_data"
    assert r["blocking_issues"]


def test_ready_for_shadow_collection():
    r = _a(sr=[], se=[_se()])
    assert r["verdict"] == "ready_for_shadow_collection"


def test_not_ready_no_candidates():
    r = _a(sr=[_sr(would_attach_without_shadow=False, decision_reason="no_candidates",
                   match_reason="no_candidates", match_score=0.0) for _ in range(10)])
    assert r["verdict"] == "not_ready"
    assert any("source candidates" in b for b in r["blocking_issues"])


def test_not_ready_low_overlap():
    r = _a(sr=[_sr(would_attach_without_shadow=False, decision_reason="low_overlap",
                   match_reason="low_overlap", match_score=0.3) for _ in range(10)])
    assert r["verdict"] == "not_ready"
    assert any("timestamp" in b for b in r["blocking_issues"])


def test_not_ready_low_text_similarity():
    r = _a(sr=[_sr(would_attach_without_shadow=False, decision_reason="low_text_similarity",
                   match_reason="low_text_similarity", match_score=0.3) for _ in range(10)])
    assert r["verdict"] == "not_ready"
    assert any("transcripts" in b for b in r["blocking_issues"])


def test_not_ready_ambiguous():
    r = _a(sr=[_sr(would_attach_without_shadow=False, decision_reason="ambiguous",
                   match_reason="ambiguous", match_score=0.0) for _ in range(10)])
    assert r["verdict"] == "not_ready"
    assert any("ambiguous" in b for b in r["blocking_issues"])


def test_ready_for_active_with_suggested_patch():
    r = _a(sr=[_sr() for _ in range(10)])
    assert r["verdict"] == "ready_for_active_source_reconcile_canary"
    p = r["suggested_patch"]
    assert p["source_reconcile_enabled"] is True
    assert p["source_reconcile_shadow_mode"] is False
    assert p["source_reconcile_min_match_score"] >= 0.62


def test_active_canary_running():
    r = _a(sr=[_sr(actual_attach=True, decision_reason="allowed") for _ in range(10)])
    assert r["verdict"] == "active_canary_running"


def test_signal_unknown_high_low_hints_warning():
    se = [_se(speaker_side_counts={"unknown": 1}, speaker_unknown_side_count=1,
              speaker_hint_source_count=0) for _ in range(10)]
    r = _a(sr=[_sr() for _ in range(5)], se=se)
    assert any("speaker_identity_hints" in w for w in r["warnings"])


def test_signal_engine_error_warning():
    se = [_se(error_kind="timeout") for _ in range(10)]
    r = _a(sr=[_sr() for _ in range(5)], se=se)
    assert any("timeout/exception" in w for w in r["warnings"])


def test_output_no_raw_values():
    sr = [_sr() for _ in range(5)]
    se = [_se() for _ in range(5)]
    blob = json.dumps(_a(sr=sr, se=se), ensure_ascii=False)
    # анализатор не выводит сырые строки/тексты/ids — только агрегаты/категории
    for raw in ("SM_1", "track_2", "seg-1", "synthetic", "SOURCE_RECONCILE_TRACE"):
        assert raw not in blob


def test_extract_all_from_lines():
    sr_line = "INFO SOURCE_RECONCILE_TRACE " + json.dumps(_sr())
    se_line = "INFO SIGNAL_ENGINE_TRACE " + json.dumps(_se())
    ev = extract_all_canary_trace_events_from_lines([sr_line, "noise", se_line])
    assert len(ev["source_reconcile"]) == 1
    assert len(ev["signal_engine"]) == 1


def test_cli(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(["INFO SOURCE_RECONCILE_TRACE " + json.dumps(_sr()) for _ in range(5)]),
                   encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.canary_readiness_analysis", str(log)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["verdict"] == "ready_for_active_source_reconcile_canary"


def test_cli_missing_file(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.canary_readiness_analysis", str(tmp_path / "no.log")],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 2


# --- Этап 13: фильтрация по meeting/session ---

def test_filter_by_meeting_changes_counts():
    sr = [_sr(meeting_id="42") for _ in range(6)] + [_sr(meeting_id="99") for _ in range(4)]
    r = analyze_canary_readiness_from_events(
        source_reconcile_events=sr, signal_engine_events=[], meeting_id="42")
    assert r["source_reconciliation"]["total"] == 6
    assert r["trace_filters"]["source_reconcile"]["input_count"] == 10
    assert r["trace_filters"]["source_reconcile"]["output_count"] == 6
    assert r["trace_filters"]["filters_applied"]["meeting_id"] is True


def test_mixed_meetings_without_filter_adds_warning():
    sr = [_sr(meeting_id="42") for _ in range(5)] + [_sr(meeting_id="99") for _ in range(5)]
    r = analyze_canary_readiness_from_events(source_reconcile_events=sr, signal_engine_events=[])
    assert any("несколько meeting_id" in w for w in r["warnings"])
    assert r["trace_scope"]["has_mixed_meetings"] is True


def test_filtered_no_events_is_no_data():
    sr = [_sr(meeting_id="42") for _ in range(5)]
    r = analyze_canary_readiness_from_events(
        source_reconcile_events=sr, signal_engine_events=[], meeting_id="does-not-exist")
    assert r["verdict"] == "no_data"


def test_filter_output_has_hashes_not_raw_ids():
    sr = [_sr(meeting_id="secret-meeting-id") for _ in range(5)]
    r = analyze_canary_readiness_from_events(
        source_reconcile_events=sr, signal_engine_events=[], meeting_id="secret-meeting-id")
    blob = json.dumps(r, ensure_ascii=False)
    assert "secret-meeting-id" not in blob
    assert r["trace_filters"]["filter_hashes"]["meeting_id"] is not None


def test_cli_require_single_meeting_exit4(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = ["INFO SOURCE_RECONCILE_TRACE " + json.dumps(_sr(meeting_id="42")),
             "INFO SOURCE_RECONCILE_TRACE " + json.dumps(_sr(meeting_id="99"))]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.canary_readiness_analysis", str(log),
         "--require-single-meeting"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 4
    assert json.loads(proc.stdout)["trace_scope"]["has_mixed_meetings"] is True


def test_cli_meeting_filter(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = ["INFO SOURCE_RECONCILE_TRACE " + json.dumps(_sr(meeting_id="42")) for _ in range(5)]
    lines += ["INFO SOURCE_RECONCILE_TRACE " + json.dumps(_sr(meeting_id="99")) for _ in range(5)]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.canary_readiness_analysis", str(log),
         "--meeting-id", "42", "--require-single-meeting"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0  # отфильтровано до одной встречи
    out = json.loads(proc.stdout)
    assert out["source_reconciliation"]["total"] == 5
