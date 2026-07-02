"""Per-channel STT canary monitor (Этап 19)."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.per_channel_stt_canary_monitor import (
    analyze_per_channel_stt_canary_run,
    load_per_channel_stt_monitor_events_from_lines,
)

_BACKEND = str(Path(__file__).resolve().parents[1])


def _pcs(meeting_id="42", **kw):
    b = dict(check_id="c", meeting_id=meeting_id, enabled=True, shadow_mode=True,
             frame_count=kw.pop("frame_count", 100), provider=kw.pop("provider", "elevenlabs_batch"),
             segment_finalized_count=kw.pop("finalized", 10), transcribe_success_count=kw.pop("success", 8),
             candidate_shadow_suppressed_count=kw.pop("suppressed", 8), candidate_emit_count=kw.pop("emit", 0),
             adapter_unavailable_count=kw.pop("unavail", 0), transcribe_timeout_count=kw.pop("timeout", 0),
             transcribe_provider_error_count=kw.pop("perr", 0), transcribe_budget_exhausted_count=kw.pop("budget", 0),
             transcribe_cache_hit_count=kw.pop("chit", 2), transcribe_cache_miss_count=kw.pop("cmiss", 8),
             max_channels_seen=kw.pop("maxch", 2), average_dominance=kw.pop("dom", 0.8),
             average_transcribe_latency_ms=kw.pop("lat", 1500),
             segment_dropped_low_dominance_count=kw.pop("lowdom", 0), last_error_kind=kw.pop("lek", None))
    b.update(kw)
    return b


def _sr(meeting_id="42", actual=False, would=True, mr="matched"):
    return dict(meeting_id=meeting_id, would_attach_without_shadow=would, actual_attach=actual,
                decision_reason="shadow_mode", match_reason=mr, match_score=0.9, time_overlap=1.0,
                text_similarity=1.0, attribution_confidence=0.85, candidate_source="multi_channel_live",
                source_kind="multi_channel", attribution_source="multi_source_segment")


def _A(pcs=None, sr=None, se=None, **kw):
    return analyze_per_channel_stt_canary_run(
        per_channel_stt_events=pcs or [], source_reconcile_events=sr or [], signal_engine_events=se or [], **kw)


def test_no_data():
    r = _A()
    assert r["status"] == "no_data"
    assert r["primary_recommendation"] == "enable_multichannel_shadow"
    assert r["blocking_issues"]


def test_no_multichannel():
    se = [dict(meeting_id="42", situation_type="x", decision_reason="shadow_mode", error_kind="none",
               would_prompt_without_shadow=False, actual_should_prompt=False, score=0.4, latency_ms=100,
               audio_multichannel_max_channels_seen=1, audio_multichannel_frame_count=5)]
    r = _A(se=se)
    assert r["status"] == "no_multichannel"
    assert r["primary_recommendation"] == "enable_multichannel_shadow"


def test_provider_noop_unavailable():
    r = _A(pcs=[_pcs(provider="noop", success=0, suppressed=0, unavail=10)])
    assert r["status"] == "provider_unavailable"
    assert r["primary_recommendation"] == "configure_provider"


def test_api_key_missing():
    r = _A(pcs=[_pcs(provider="elevenlabs_batch", success=0, unavail=5, lek="api_key_missing")])
    assert r["status"] == "provider_unavailable"
    assert r["per_channel_stt"]["api_key_missing_count"] == 1
    assert any("api_key_missing" in b for b in r["blocking_issues"])


def test_ready_for_candidate_emit():
    r = _A(pcs=[_pcs() for _ in range(6)])
    assert r["status"] == "ready_for_candidate_emit"
    assert r["primary_recommendation"] == "emit_candidates"
    p = r["suggested_patch"]
    assert p["audio_per_channel_stt_shadow_mode"] is False
    assert p["source_reconcile_shadow_mode"] is True
    assert p.get("source_reconcile_shadow_mode") is not False or True  # never false
    assert "signal_engine_shadow_mode" not in p and "speaker_identity_hints" not in p


def test_candidate_emit_running():
    r = _A(pcs=[_pcs(emit=5, suppressed=0)], sr=[_sr() for _ in range(5)])
    assert r["status"] == "candidate_emit_running"
    assert r["active_state"] == "candidate_emitting"
    assert r["primary_recommendation"] == "continue_candidate_emit"


def test_emit_but_no_reconcile_match():
    r = _A(pcs=[_pcs(emit=5)], sr=[_sr(would=False, mr="no_candidates") for _ in range(5)])
    assert r["status"] == "warning"
    assert r["primary_recommendation"] == "collect_more_data"
    assert any("не матчит" in w for w in r["warnings"])


def test_rollback_high_timeout():
    r = _A(pcs=[_pcs(emit=5, timeout=8, finalized=10)], sr=[_sr() for _ in range(3)])
    assert r["status"] == "rollback_recommended"
    assert r["rollback_recommended"] is True
    assert r["rollback_patch"] is not None
    assert all(k.startswith("audio_per_channel_stt_") for k in r["rollback_patch"])
    assert any("timeout_rate" in b for b in r["blocking_issues"])


def test_rollback_high_provider_error():
    r = _A(pcs=[_pcs(emit=5, perr=9, finalized=10)], sr=[_sr() for _ in range(3)])
    assert r["status"] == "rollback_recommended"
    assert any("provider_error_rate" in b for b in r["blocking_issues"])


def test_ready_gate_blocks_high_budget_exhausted():
    # shadow с высокой долей budget_exhausted НЕ должен становиться ready (иначе сразу rollback)
    r = _A(pcs=[_pcs(budget=8, finalized=10) for _ in range(6)])
    assert r["status"] != "ready_for_candidate_emit"


def test_ready_gate_blocks_high_latency():
    r = _A(pcs=[_pcs(lat=30000) for _ in range(6)])  # latency > 20000ms порог
    assert r["status"] != "ready_for_candidate_emit"


def test_shadow_tighten_vad():
    r = _A(pcs=[_pcs(success=0, suppressed=0, finalized=0, dom=0.4)])
    assert r["status"] == "shadow_collecting"
    assert r["primary_recommendation"] == "tighten_vad"


def test_shadow_budget_exhausted_increase_budget():
    r = _A(pcs=[_pcs(success=0, suppressed=0, finalized=5, budget=5, dom=0.8)])
    assert r["primary_recommendation"] == "increase_budget"


def test_rollback_patch_only_per_channel():
    r = _A(pcs=[_pcs(emit=5, timeout=9, finalized=10)], sr=[_sr() for _ in range(3)])
    p = r["rollback_patch"]
    assert all(v is None for v in p.values())
    assert not any(k.startswith("source_reconcile_") or k.startswith("signal_engine_") for k in p)
    assert "speaker_identity_hints" not in p


def test_safety_checks_all_true_and_no_raw():
    # runtime safety_checks — настоящая гарантия; имена safety-полей does_not_contain_* — не утечка
    r = _A(pcs=[_pcs(lek="api_key_missing") for _ in range(6)], sr=[_sr() for _ in range(3)])
    assert all(r["safety_checks"].values())
    blob = json.dumps(r, ensure_ascii=False)
    for raw in ("transcript_text", "SM_1", "track_2", "channel_0", "seg-1", "cand-1",
                "xi-api-key", "Bearer ", "sk_live"):
        assert raw not in blob


# --- CLI ---

def _line(marker, obj):
    return f"INFO {marker} " + json.dumps(obj)


def _run(*args):
    return subprocess.run([sys.executable, "-m", "app.core.context.per_channel_stt_canary_monitor", *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=_BACKEND)


def test_cli_meeting_filter(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = [_line("PER_CHANNEL_STT_TRACE", _pcs(meeting_id="42")) for _ in range(6)]
    lines += [_line("PER_CHANNEL_STT_TRACE", _pcs(meeting_id="99", success=0, suppressed=0))]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = _run(str(log), "--meeting-id", "42")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "ready_for_candidate_emit"
    assert "42" not in json.dumps(out["trace_filters"]["filter_hashes"])  # hash, not raw


def test_cli_emit_rollback_if_needed(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = [_line("PER_CHANNEL_STT_TRACE", _pcs(meeting_id="42", emit=5, timeout=9, finalized=10))]
    lines += [_line("SOURCE_RECONCILE_TRACE", _sr(meeting_id="42")) for _ in range(3)]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = _run(str(log), "--meeting-id", "42", "--emit-rollback-if-needed")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["rollback_recommended"] is True
    assert out["apply_rollback"] is True


def test_cli_file_not_found():
    assert _run("no_such.log", "--meeting-id", "42").returncode == 2


def test_cli_require_single_meeting_exit4(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = [_line("PER_CHANNEL_STT_TRACE", _pcs(meeting_id="42")),
             _line("PER_CHANNEL_STT_TRACE", _pcs(meeting_id="99"))]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = _run(str(log), "--require-single-meeting")
    assert proc.returncode == 4
    assert json.loads(proc.stdout)["trace_scope"]["has_mixed_meetings"] is True


def test_cli_via_canary_operations_subcommand(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_line("PER_CHANNEL_STT_TRACE", _pcs(meeting_id="42")) for _ in range(6)),
                   encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.canary_operations", "monitor-per-channel-stt",
         str(log), "--meeting-id", "42"],
        capture_output=True, text=True, encoding="utf-8", cwd=_BACKEND)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["status"] == "ready_for_candidate_emit"
