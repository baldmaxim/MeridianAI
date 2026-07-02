"""Canary readiness harness (Этап 12): synthetic end-to-end chain."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.source_reconcile_canary_harness import (
    get_builtin_canary_case,
    run_builtin_canary_cases,
    run_source_reconcile_canary_case,
)


def _case(name):
    return get_builtin_canary_case(name)


def test_safe_match_shadow():
    r = run_source_reconcile_canary_case(_case("safe_match"), active=False)
    assert r["would_attach_without_shadow"] is True
    assert r["actual_attach"] is False
    assert r["speaker_audio_stable_link_count"] == 0


def test_safe_match_active():
    r = run_source_reconcile_canary_case(_case("safe_match"), active=True)
    assert r["actual_attach"] is True
    assert r["speaker_audio_stable_link_count"] >= 1
    assert r["speaker_side_counts"].get("counterparty", 0) >= 1


def test_unsafe_primary_blocked():
    r = run_source_reconcile_canary_case(_case("unsafe_primary_blocked"), active=True)
    assert r["actual_attach"] is False
    assert r["matched"] is False or r["decision_reason"] != "allowed"


def test_ambiguous_blocked():
    r = run_source_reconcile_canary_case(_case("ambiguous_blocked"), active=True)
    assert r["actual_attach"] is False
    assert r["match_reason"] == "ambiguous"


def test_no_hint_unknown():
    r = run_source_reconcile_canary_case(_case("no_hint_unknown"), active=True)
    assert r["actual_attach"] is True
    assert r["speaker_audio_stable_link_count"] >= 1  # link есть
    assert r["speaker_side_counts"].get("counterparty", 0) == 0  # side unknown


def test_low_similarity_rejected():
    r = run_source_reconcile_canary_case(_case("low_similarity_rejected"), active=True)
    assert r["actual_attach"] is False


def test_time_only_strict():
    r = run_source_reconcile_canary_case(_case("time_only_strict"), active=True)
    assert r["matched"] is True
    assert r["actual_attach"] is True


def test_leak_check_all_false_and_no_raw_in_result():
    for name in ("safe_match", "no_hint_unknown", "time_only_strict"):
        for active in (False, True):
            r = run_source_reconcile_canary_case(_case(name), active=active)
            assert r["leak_check"] == {
                "contains_raw_text": False, "contains_raw_speaker_label": False,
                "contains_raw_source_id": False, "contains_raw_segment_id": False}
            blob = json.dumps(r, ensure_ascii=False)
            for raw in ("synthetic", "SM_1", "track_2", "seg-1", "cand-1"):
                assert raw not in blob


def test_public_payload_no_source_attribution():
    r = run_source_reconcile_canary_case(_case("safe_match"), active=True)
    assert r["public_payload_contains_source_attribution"] is False


def test_run_builtin_all():
    out = run_builtin_canary_cases(active=False)
    assert len(out) == 7
    assert all(o["actual_attach"] is False for o in out)  # shadow → ничего не прикреплено


def test_invalid_case_raises():
    import pytest
    with pytest.raises(ValueError):
        run_source_reconcile_canary_case({"name": "bad"})  # нет committed_segment


# --- CLI ---

def test_cli_scenario_all():
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.source_reconcile_canary_harness", "--scenario", "all"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert isinstance(out, list) and len(out) == 7
    # leak-safe: нет raw в stdout
    for raw in ("synthetic", "SM_1", "track_2", "seg-1"):
        assert raw not in proc.stdout


def test_cli_case_file_missing(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.source_reconcile_canary_harness",
         "--case-file", str(tmp_path / "no.json")],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 2
