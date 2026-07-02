"""Active canary monitor + rollback recommendation (Этап 14)."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.active_canary_monitor import analyze_active_canary_run

_BACKEND = str(Path(__file__).resolve().parents[1])


def _sr(*, actual=False, would=True, match_reason="matched", decision_reason="allowed",
        score=0.9, overlap=1.0, sim=1.0, meeting_id=None):
    e = dict(would_attach_without_shadow=would, actual_attach=actual,
             decision_reason=decision_reason, match_reason=match_reason, match_score=score,
             time_overlap=overlap, text_similarity=sim, attribution_confidence=0.85,
             candidate_source="multi_channel_live", source_kind="multi_channel",
             attribution_source="multi_source_segment")
    if meeting_id is not None:
        e["meeting_id"] = meeting_id
    return e


def _nocand(meeting_id=None):
    e = dict(would_attach_without_shadow=False, actual_attach=False, decision_reason="no_candidates",
             match_reason="no_candidates", match_score=0.0, time_overlap=0.0, text_similarity=0.0,
             attribution_confidence=0.0)
    if meeting_id is not None:
        e["meeting_id"] = meeting_id
    return e


def _se(*, unknown=0, hint=1, audio=0, err="none", lat=120, meeting_id=None):
    e = dict(situation_type="price_pressure", decision_reason="shadow_mode", error_kind=err,
             would_prompt_without_shadow=True, actual_should_prompt=False, score=0.4, latency_ms=lat,
             speaker_side_counts={"unknown": unknown} if unknown else {"counterparty": 1},
             speaker_unknown_side_count=unknown, speaker_count=1, speaker_context_chars=10,
             speaker_hint_source_count=hint, speaker_audio_linked_count=audio)
    if meeting_id is not None:
        e["meeting_id"] = meeting_id
    return e


def _A(sr=None, se=None, **kw):
    return analyze_active_canary_run(
        source_reconcile_events=sr or [], signal_engine_events=se or [], **kw)


# --- статусы / рекомендации ---

def test_no_data():
    r = _A()
    assert r["status"] == "no_data"
    assert r["active_state"] == "no_reconcile"
    assert r["primary_recommendation"] == "remain_in_shadow"
    assert r["blocking_issues"]
    assert r["rollback_recommended"] is False
    assert r["rollback_patch"] is None


def test_signal_only_shadow():
    r = _A(se=[_se() for _ in range(5)])
    assert r["status"] == "shadow_only"
    assert r["active_state"] == "no_reconcile"
    assert r["primary_recommendation"] == "remain_in_shadow"
    assert any("нет SOURCE_RECONCILE_TRACE" in w for w in r["warnings"])


def test_shadow_would_no_actual():
    r = _A(sr=[_sr(actual=False) for _ in range(12)])
    assert r["status"] == "shadow_only"
    assert r["active_state"] == "shadow_only"
    assert r["primary_recommendation"] == "remain_in_shadow"
    assert r["rollback_recommended"] is False


def test_healthy_active_continue():
    sr = [_sr(actual=True) for _ in range(3)] + [_nocand() for _ in range(9)]
    r = _A(sr=sr, se=[_se() for _ in range(12)])
    assert r["status"] == "healthy"
    assert r["active_state"] == "active_attaching"
    assert r["primary_recommendation"] == "continue_active"
    assert r["rollback_recommended"] is False
    assert r["rollback_patch"] is None
    assert r["source_reconciliation"]["score_p50"] == 0.9  # matched-only, не занижено no_candidates


def test_active_high_ambiguous_rollback():
    sr = [_sr(actual=True, match_reason="ambiguous") for _ in range(2)] + [_nocand() for _ in range(10)]
    r = _A(sr=sr)
    assert r["status"] == "rollback_recommended"
    assert r["rollback_recommended"] is True
    assert r["rollback_patch"] is not None
    assert any("ambiguous" in b for b in r["blocking_issues"])


def test_active_high_low_overlap_no_attach_check_timestamps():
    sr = [_sr(actual=False, would=False, match_reason="low_overlap", decision_reason="low_overlap",
              score=0.0, overlap=0.1) for _ in range(12)]
    r = _A(sr=sr)
    assert r["active_state"] == "shadow_only"  # actual=0
    assert r["primary_recommendation"] == "check_multichannel_timestamps"
    assert r["rollback_recommended"] is False


def test_active_high_low_text_similarity_tighten():
    sr = [_sr(actual=False, would=False, match_reason="low_text_similarity",
              decision_reason="low_text_similarity", score=0.0, sim=0.1) for _ in range(12)]
    r = _A(sr=sr)
    assert r["primary_recommendation"] == "tighten_thresholds"


def test_active_low_score_rollback():
    sr = [_sr(actual=True, score=0.4) for _ in range(2)] + [_nocand() for _ in range(10)]
    r = _A(sr=sr)
    assert r["rollback_recommended"] is True
    assert any("score_p50" in b for b in r["blocking_issues"])


def test_active_attach_rate_too_high_rollback():
    sr = [_sr(actual=True) for _ in range(5)] + [_nocand() for _ in range(5)]  # 0.5
    r = _A(sr=sr)
    assert r["rollback_recommended"] is True
    assert any("actual_attach_rate" in b for b in r["blocking_issues"])


def test_low_hint_coverage_add_hints():
    sr = [_sr(actual=True) for _ in range(2)] + [_nocand() for _ in range(10)]
    se = [_se(unknown=1, hint=0) for _ in range(12)]
    r = _A(sr=sr, se=se)
    assert r["status"] == "warning"
    assert r["primary_recommendation"] == "add_speaker_identity_hints"
    assert r["rollback_recommended"] is False
    assert any("speaker_identity_hints" in w for w in r["warnings"])


def test_signal_timeout_warning_not_rollback():
    sr = [_sr(actual=True) for _ in range(2)] + [_nocand() for _ in range(10)]
    se = [_se(unknown=0, hint=1, err="timeout") for _ in range(12)]
    r = _A(sr=sr, se=se)
    assert r["status"] == "healthy"
    assert r["primary_recommendation"] == "continue_active"
    assert r["rollback_recommended"] is False
    assert any("timeout/exception" in w for w in r["warnings"])


def test_small_sample_collect():
    sr = [_sr(actual=True)] + [_nocand() for _ in range(3)]
    r = _A(sr=sr, se=[_se() for _ in range(4)])
    assert r["status"] == "collecting"
    assert r["primary_recommendation"] == "collect_more_data"
    assert r["rollback_recommended"] is False


def test_rollback_patch_only_source_reconcile_none():
    sr = [_sr(actual=True) for _ in range(6)] + [_nocand() for _ in range(4)]  # attach 0.6 -> rollback
    r = _A(sr=sr)
    p = r["rollback_patch"]
    assert p is not None
    assert all(k.startswith("source_reconcile_") for k in p)
    assert all(v is None for v in p.values())
    assert "speaker_identity_hints" not in p
    assert not any(k.startswith("signal_engine_") for k in p)


def test_safety_checks_all_true():
    sr = [_sr(actual=True) for _ in range(3)] + [_nocand() for _ in range(9)]
    r = _A(sr=sr, se=[_se() for _ in range(12)])
    assert all(r["safety_checks"].values())


def test_output_no_raw_values():
    sr = [_sr(actual=True) for _ in range(3)] + [_nocand() for _ in range(9)]
    blob = json.dumps(_A(sr=sr, se=[_se() for _ in range(12)]), ensure_ascii=False)
    for raw in ("transcript", "audio_source_id", "channel_label", "SM_1", "track_2",
                "seg-1", "cand-1", "Speaker SM"):
        assert raw not in blob


def test_severe_speaker_low_attach_adds_hints_not_rollback():
    # unknown>0.7, hint<0.2, audio>0.5, но attach rate низкий (2/12=0.167) → add_hints, НЕ rollback
    sr = [_sr(actual=True) for _ in range(2)] + [_nocand() for _ in range(10)]
    se = [_se(unknown=1, hint=0, audio=1) for _ in range(12)]
    r = _A(sr=sr, se=se)
    assert r["status"] == "warning"
    assert r["primary_recommendation"] == "add_speaker_identity_hints"
    assert r["rollback_recommended"] is False


def test_severe_speaker_high_attach_rolls_back():
    # та же деградация, но attach «слишком активен» (6/10=0.6) → rollback (через attach-rate blocker)
    sr = [_sr(actual=True) for _ in range(6)] + [_nocand() for _ in range(4)]
    se = [_se(unknown=1, hint=0, audio=1) for _ in range(10)]
    r = _A(sr=sr, se=se)
    assert r["rollback_recommended"] is True
    assert r["primary_recommendation"] == "rollback_source_reconcile"


def test_cooccurring_failure_modes_surfaced_in_notes():
    # actual=0, would=0: low_overlap И low_text_similarity оба повышены → primary один, в notes — оба
    sr = [_sr(actual=False, would=False, match_reason="low_overlap", decision_reason="low_overlap",
              score=0.0, overlap=0.1) for _ in range(4)]
    sr += [_sr(actual=False, would=False, match_reason="low_text_similarity",
               decision_reason="low_text_similarity", score=0.0, sim=0.1) for _ in range(4)]
    sr += [_nocand() for _ in range(2)]
    r = _A(sr=sr)
    assert r["primary_recommendation"] == "check_multichannel_timestamps"  # priority
    assert any("low_overlap_rate" in n for n in r["notes"])
    assert any("low_text_similarity_rate" in n for n in r["notes"])  # вторая причина не скрыта


def test_actual_to_would_ratio():
    sr = [_sr(actual=True) for _ in range(2)] + [_sr(actual=False) for _ in range(2)] + [_nocand() for _ in range(8)]
    r = _A(sr=sr)
    # would=4 (4 would-attach events), actual=2 -> ratio 0.5
    assert r["source_reconciliation"]["actual_to_would_ratio"] == 0.5


# --- CLI ---

def _line(marker, obj):
    return f"INFO {marker} " + json.dumps(obj)


def _run(*args):
    return subprocess.run([sys.executable, "-m", "app.core.context.active_canary_monitor", *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=_BACKEND)


def test_cli_meeting_filter(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = [_line("SOURCE_RECONCILE_TRACE", _sr(actual=True, meeting_id="42")) for _ in range(3)]
    lines += [_line("SOURCE_RECONCILE_TRACE", _nocand(meeting_id="42")) for _ in range(9)]
    lines += [_line("SOURCE_RECONCILE_TRACE", _sr(actual=True, meeting_id="99")) for _ in range(10)]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = _run(str(log), "--meeting-id", "42")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["source_reconciliation"]["total"] == 12  # только встреча 42
    assert "42" not in json.dumps(out["trace_filters"]["filter_hashes"])  # хэш, не raw id


def test_cli_emit_rollback_if_needed(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = [_line("SOURCE_RECONCILE_TRACE", _sr(actual=True, meeting_id="42")) for _ in range(8)]
    lines += [_line("SOURCE_RECONCILE_TRACE", _nocand(meeting_id="42")) for _ in range(2)]  # attach 0.8
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = _run(str(log), "--meeting-id", "42", "--emit-rollback-if-needed")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["rollback_recommended"] is True
    assert out["apply_rollback"] is True
    assert out["rollback_patch"] is not None
    assert out["rollback_endpoint_template"] == "/api/meetings/{meeting_id}/ai-settings"


def test_cli_file_not_found():
    proc = _run("no_such.log", "--meeting-id", "42")
    assert proc.returncode == 2


def test_cli_require_single_meeting_exit4(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = [_line("SOURCE_RECONCILE_TRACE", _sr(actual=True, meeting_id="42")),
             _line("SOURCE_RECONCILE_TRACE", _sr(actual=True, meeting_id="99"))]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = _run(str(log), "--require-single-meeting")
    assert proc.returncode == 4
    assert json.loads(proc.stdout)["trace_scope"]["has_mixed_meetings"] is True


def test_cli_via_canary_operations_monitor(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = [_line("SOURCE_RECONCILE_TRACE", _sr(actual=True, meeting_id="42")) for _ in range(3)]
    lines += [_line("SOURCE_RECONCILE_TRACE", _nocand(meeting_id="42")) for _ in range(9)]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.canary_operations", "monitor", str(log),
         "--meeting-id", "42"],
        capture_output=True, text=True, encoding="utf-8", cwd=_BACKEND)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["status"] == "healthy"
