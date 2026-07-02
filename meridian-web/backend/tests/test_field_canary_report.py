"""Unified field canary report (Этап 20)."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.field_canary_report import analyze_field_canary_report

_BACKEND = str(Path(__file__).resolve().parents[1])


def _pcs(meeting_id="42", **kw):
    b = dict(check_id="c", meeting_id=meeting_id, enabled=True, shadow_mode=True, frame_count=100,
             provider=kw.pop("provider", "elevenlabs_batch"), segment_finalized_count=kw.pop("fin", 10),
             transcribe_success_count=kw.pop("succ", 8), candidate_shadow_suppressed_count=kw.pop("supp", 8),
             candidate_emit_count=kw.pop("emit", 0), adapter_unavailable_count=kw.pop("unav", 0),
             transcribe_timeout_count=kw.pop("to", 0), transcribe_provider_error_count=kw.pop("pe", 0),
             transcribe_budget_exhausted_count=kw.pop("be", 0), transcribe_cache_hit_count=4,
             transcribe_cache_miss_count=8, max_channels_seen=kw.pop("maxch", 2), average_dominance=0.8,
             average_transcribe_latency_ms=1500, provider_calls_used=kw.pop("calls", 8),
             provider_audio_seconds_used=kw.pop("sec", 120.0), last_error_kind=kw.pop("lek", None))
    b.update(kw)
    return b


def _sr(meeting_id="42", actual=False, would=True, mr="matched"):
    return dict(meeting_id=meeting_id, would_attach_without_shadow=would, actual_attach=actual,
                decision_reason="shadow_mode", match_reason=mr, match_score=0.9, time_overlap=1.0,
                text_similarity=1.0, attribution_confidence=0.85, candidate_source="multi_channel_live",
                source_kind="multi_channel", attribution_source="multi_source_segment")


def _se(meeting_id="42", unknown=1, hint=0, mc=2):
    return dict(meeting_id=meeting_id, situation_type="x", decision_reason="shadow_mode", error_kind="none",
                would_prompt_without_shadow=False, actual_should_prompt=False, score=0.4, latency_ms=120,
                speaker_side_counts={"unknown": unknown} if unknown else {"counterparty": 1},
                speaker_unknown_side_count=unknown, speaker_count=1, speaker_context_chars=10,
                speaker_hint_source_count=hint, speaker_audio_linked_count=2,
                audio_multichannel_max_channels_seen=mc, audio_multichannel_frame_count=5)


def _A(pcs=None, sr=None, se=None, cost=None):
    return analyze_field_canary_report(
        per_channel_stt_events=pcs or [], source_reconcile_events=sr or [], signal_engine_events=se or [],
        provider_cost_per_minute=cost)


def test_no_data():
    r = _A()
    assert r["status"] == "no_data"
    assert r["primary_recommendation"] == "enable_multichannel_shadow"


def test_multichannel_absent_not_ready():
    r = _A(se=[_se(mc=1)])
    assert r["status"] == "not_ready"
    assert r["primary_recommendation"] == "enable_multichannel_shadow"


def test_provider_unavailable():
    r = _A(pcs=[_pcs(provider="noop", succ=0, supp=0, unav=10)])
    assert r["status"] == "not_ready"
    assert r["primary_recommendation"] == "configure_provider"


def test_per_channel_shadow_ready():
    r = _A(pcs=[_pcs() for _ in range(6)])
    assert r["status"] in ("candidate_emit_ready", "per_channel_shadow_ready")
    assert r["per_channel_stt"]["transcribe_success_count"] == 8
    assert r["per_channel_stt"]["candidate_shadow_suppressed_count"] == 8


def test_source_reconcile_ready():
    r = _A(pcs=[_pcs(emit=5)], sr=[_sr() for _ in range(10)])
    assert r["status"] == "source_reconcile_ready"
    assert r["patches"]["source_reconcile_active_patch"] is not None


def test_active_running_healthy():
    # реалистично: часть attach + много no_candidates → attach_rate низкий, healthy
    sr = [_sr(actual=True) for _ in range(2)] + [_sr(would=False, mr="no_candidates") for _ in range(8)]
    r = _A(pcs=[_pcs(emit=5)], sr=sr)
    assert r["status"] in ("healthy", "active_source_reconcile_running")


def test_needs_hints():
    r = _A(pcs=[_pcs(emit=5)], sr=[_sr() for _ in range(5)],
           se=[_se(unknown=1, hint=0) for _ in range(10)])
    assert r["status"] == "needs_hints"
    assert r["primary_recommendation"] == "add_speaker_identity_hints"


def test_rollback_per_channel():
    r = _A(pcs=[_pcs(emit=5, to=8, fin=10)], sr=[_sr() for _ in range(3)])
    assert r["status"] == "rollback_recommended"
    assert r["primary_recommendation"] == "rollback_per_channel_stt"
    assert all(k.startswith("audio_per_channel_stt_") for k in r["patches"]["per_channel_rollback_patch"])


def test_rollback_source_reconcile():
    # active attach слишком высок (5/5) → active monitor rollback
    r = _A(pcs=[_pcs(emit=5)], sr=[_sr(actual=True) for _ in range(5)])
    assert r["status"] == "rollback_recommended"
    assert r["primary_recommendation"] == "rollback_source_reconcile"
    assert all(k.startswith("source_reconcile_") for k in r["patches"]["source_reconcile_rollback_patch"])


def test_cost_estimated_when_cost_passed():
    r = _A(pcs=[_pcs(calls=12, sec=180.0) for _ in range(6)], cost=0.40)
    assert r["cost_usage"]["provider_audio_minutes"] == 3.0
    assert r["cost_usage"]["estimated_cost"] == 1.2
    assert r["cost_usage"]["provider_call_count"] == 12


def test_cost_null_without_input():
    r = _A(pcs=[_pcs(sec=60.0) for _ in range(6)])
    assert r["cost_usage"]["estimated_cost"] is None
    assert r["cost_usage"]["cost_per_minute_used"] is None


def test_patches_do_not_enable_signal_or_modify_hints():
    r = _A(pcs=[_pcs(emit=5)], sr=[_sr() for _ in range(10)])
    assert r["safety_checks"]["patches_do_not_enable_signal_engine_active"] is True
    assert r["safety_checks"]["patches_do_not_modify_speaker_identity_hints"] is True
    for p in r["patches"].values():
        if isinstance(p, dict):
            assert "speaker_identity_hints" not in p
            assert p.get("signal_engine_shadow_mode") is not False


def test_safety_all_true_and_no_raw():
    r = _A(pcs=[_pcs(lek="api_key_missing") for _ in range(6)], sr=[_sr() for _ in range(3)],
           se=[_se() for _ in range(3)])
    assert all(r["safety_checks"].values())
    blob = json.dumps(r, ensure_ascii=False)
    for raw in ("transcript_text", "pcm16_mono", "RIFF", "SM_1", "track_2", "channel_0", "seg-1",
                "cand-1", "xi-api-key", "Authorization", "Bearer "):
        assert raw not in blob


# --- CLI ---

def _line(marker, obj):
    return f"INFO {marker} " + json.dumps(obj)


def _run(*args):
    return subprocess.run([sys.executable, "-m", "app.core.context.field_canary_report", *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=_BACKEND)


def test_cli_basic(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_line("PER_CHANNEL_STT_TRACE", _pcs()) for _ in range(6)), encoding="utf-8")
    proc = _run(str(log), "--meeting-id", "42")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert "status" in out and all(out["safety_checks"].values())
    assert "42" not in json.dumps(out["trace_filters"]["filter_hashes"])  # hash, not raw


def test_cli_emit_next_patch(tmp_path: Path):
    log = tmp_path / "app.log"
    lines = [_line("PER_CHANNEL_STT_TRACE", _pcs(emit=5))]
    lines += [_line("SOURCE_RECONCILE_TRACE", _sr()) for _ in range(10)]
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = _run(str(log), "--meeting-id", "42", "--emit-next-patch")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert "next_patch_name" in out and out["patch"] is not None


def test_cli_emit_next_patch_none_exit4(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_line("PER_CHANNEL_STT_TRACE", _pcs(provider="noop", succ=0, supp=0, unav=10))
                             for _ in range(6)), encoding="utf-8")
    proc = _run(str(log), "--meeting-id", "42", "--emit-next-patch")
    assert proc.returncode == 4
    assert json.loads(proc.stdout)["error"] == "no_safe_next_patch"


def test_cli_output_writes_sanitized(tmp_path: Path):
    log = tmp_path / "app.log"
    out_file = tmp_path / "report.json"
    log.write_text("\n".join(_line("PER_CHANNEL_STT_TRACE", _pcs()) for _ in range(6)), encoding="utf-8")
    proc = _run(str(log), "--meeting-id", "42", "--output", str(out_file))
    assert proc.returncode == 0
    written = json.loads(out_file.read_text(encoding="utf-8"))
    assert "status" in written and "safety_checks" in written
    # written file is the report, not raw log lines
    assert "PER_CHANNEL_STT_TRACE" not in out_file.read_text(encoding="utf-8")


def test_cli_file_not_found():
    assert _run("no_such.log", "--meeting-id", "42").returncode == 2


def test_cli_via_canary_operations_field_report(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_line("PER_CHANNEL_STT_TRACE", _pcs()) for _ in range(6)), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "app.core.context.canary_operations", "field-report", str(log),
         "--meeting-id", "42"],
        capture_output=True, text=True, encoding="utf-8", cwd=_BACKEND)
    assert proc.returncode == 0
    assert "status" in json.loads(proc.stdout)
