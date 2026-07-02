"""Source Reconcile trace analysis (Этап 11)."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.source_reconcile_trace_analysis import (
    analyze_source_reconcile_traces,
    extract_source_reconcile_json_from_line,
    load_source_reconcile_events_from_lines,
    percentile,
)


def _ev(**kw) -> dict:
    base = dict(decision_reason="allowed", match_reason="matched",
                would_attach_without_shadow=True, actual_attach=True, match_score=0.9,
                time_overlap=1.0, text_similarity=1.0, attribution_confidence=0.85,
                candidate_source="multi_channel_live", source_kind="multi_channel",
                attribution_source="multi_source_segment")
    base.update(kw)
    return base


def _line(ev: dict) -> str:
    return "2026-06-30 12:00:00 INFO meridian.session SOURCE_RECONCILE_TRACE " + json.dumps(ev, ensure_ascii=False)


def test_extract_valid_line():
    obj = extract_source_reconcile_json_from_line(_line(_ev(match_score=0.7)))
    assert obj["match_score"] == 0.7


def test_extract_ignores_non_marker_and_broken():
    assert extract_source_reconcile_json_from_line("INFO some other line") is None
    assert extract_source_reconcile_json_from_line("SOURCE_RECONCILE_TRACE {broken,,") is None


def test_load_filters():
    lines = [_line(_ev()), "noise", "SOURCE_RECONCILE_TRACE {bad", _line(_ev())]
    assert len(load_source_reconcile_events_from_lines(lines)) == 2


def test_percentile():
    assert percentile([], 50) is None
    assert percentile([1, 2, 3, 4], 50) == 2.5


def test_analyze_counts_and_groups():
    events = [_ev() for _ in range(3)] + [
        _ev(decision_reason="shadow_mode", actual_attach=False, would_attach_without_shadow=True),
        _ev(decision_reason="low_overlap", match_reason="low_overlap", actual_attach=False,
            would_attach_without_shadow=False),
    ]
    s = analyze_source_reconcile_traces(events)
    assert s["total"] == 5
    assert s["would_attach_count"] == 4
    assert s["actual_attach_count"] == 3
    assert s["by_decision_reason"]["allowed"] == 3
    assert s["by_candidate_source"]["multi_channel_live"] == 5
    assert s["score"]["p50"] is not None
    assert len(s["threshold_candidates"]) == 3


def test_analyze_empty():
    s = analyze_source_reconcile_traces([])
    assert s["total"] == 0 and s["notes"]


def test_note_shadow_high_actual_zero():
    events = [_ev(decision_reason="shadow_mode", actual_attach=False) for _ in range(5)]
    s = analyze_source_reconcile_traces(events)
    assert any("source_reconcile_shadow_mode=false" in n for n in s["notes"])


def test_note_low_text_similarity():
    events = [_ev(decision_reason="low_text_similarity", match_reason="low_text_similarity",
                  actual_attach=False, would_attach_without_shadow=False) for _ in range(5)]
    s = analyze_source_reconcile_traces(events)
    assert any("low_text_similarity" in n for n in s["notes"])


def test_note_ambiguous():
    events = [_ev(decision_reason="ambiguous", match_reason="ambiguous", actual_attach=False,
                  would_attach_without_shadow=False) for _ in range(5)]
    s = analyze_source_reconcile_traces(events)
    assert any("ambiguous" in n for n in s["notes"])


def test_cli_runs(tmp_path: Path):
    log = tmp_path / "rc.log"
    log.write_text("\n".join(_line(_ev()) for _ in range(3)), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.source_reconcile_trace_analysis", str(log)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["total"] == 3


def test_cli_missing_file(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.source_reconcile_trace_analysis", str(tmp_path / "no.log")],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 2
