"""Per-channel STT canary operations toolkit (Этап 19)."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.per_channel_stt_canary_operations import (
    PER_CHANNEL_STT_OVERRIDE_KEYS,
    build_per_channel_stt_canary_plan,
    build_per_channel_stt_emit_candidates_patch,
    build_per_channel_stt_rollback_patch,
    build_per_channel_stt_shadow_patch,
)

_BACKEND = str(Path(__file__).resolve().parents[1])


def _ready_report():
    return {
        "status": "ready_for_candidate_emit",
        "blocking_issues": [], "warnings": [],
        "suggested_patch": {
            "audio_per_channel_stt_enabled": True,
            "audio_per_channel_stt_shadow_mode": False,
            "source_reconcile_enabled": True,
            "source_reconcile_shadow_mode": True,
            "source_reconcile_trace_enabled": True,
        },
    }


def _not_ready_report():
    return {"status": "shadow_collecting", "blocking_issues": [], "warnings": [], "suggested_patch": None}


def test_shadow_patch_validates():
    p = build_per_channel_stt_shadow_patch(provider="elevenlabs_batch")
    assert p["audio_per_channel_stt_enabled"] is True
    assert p["audio_per_channel_stt_shadow_mode"] is True
    assert p["audio_per_channel_stt_provider"] == "elevenlabs_batch"
    from app.services.ai_settings import validate_patch
    validate_patch(p)


def test_shadow_patch_provider_and_budget():
    p = build_per_channel_stt_shadow_patch(
        provider="elevenlabs_batch", max_provider_calls_per_meeting=30, trace_sample_rate=0.5,
        min_dominance=0.7, max_channels=2)
    assert p["audio_per_channel_stt_max_provider_calls_per_meeting"] == 30
    assert p["audio_per_channel_stt_trace_sample_rate"] == 0.5
    assert p["audio_per_channel_stt_min_dominance"] == 0.7
    # НЕ трогает source_reconcile/signal_engine/hints
    assert not any(k.startswith("source_reconcile_") or k.startswith("signal_engine_") for k in p)
    assert "speaker_identity_hints" not in p


def test_emit_candidates_none_when_not_ready():
    assert build_per_channel_stt_emit_candidates_patch(_not_ready_report()) is None
    assert build_per_channel_stt_emit_candidates_patch({"status": "no_data"}) is None


def test_emit_candidates_when_ready():
    p = build_per_channel_stt_emit_candidates_patch(_ready_report())
    assert p is not None
    assert p["audio_per_channel_stt_shadow_mode"] is False
    assert p["source_reconcile_shadow_mode"] is True


def test_emit_candidates_does_not_enable_source_reconcile_active():
    rep = _ready_report()
    rep["suggested_patch"]["source_reconcile_shadow_mode"] = False  # вредный → должен быть перезатёрт True
    p = build_per_channel_stt_emit_candidates_patch(rep)
    assert p["source_reconcile_shadow_mode"] is True  # НИКОГДА не false


def test_emit_candidates_excludes_signal_and_hints():
    rep = _ready_report()
    rep["suggested_patch"]["signal_engine_shadow_mode"] = False
    rep["suggested_patch"]["speaker_identity_hints"] = {"x": "y"}
    p = build_per_channel_stt_emit_candidates_patch(rep)
    assert "signal_engine_shadow_mode" not in p
    assert "speaker_identity_hints" not in p


def test_rollback_patch_all_none_only_per_channel():
    p = build_per_channel_stt_rollback_patch()
    assert set(p) == set(PER_CHANNEL_STT_OVERRIDE_KEYS)
    assert all(v is None for v in p.values())
    assert not any(k.startswith("source_reconcile_") or k.startswith("signal_engine_") for k in p)
    assert "speaker_identity_hints" not in p


def test_full_plan_ready_can_emit():
    plan = build_per_channel_stt_canary_plan(_ready_report())
    assert plan["status"] == "ready"
    assert plan["can_emit_candidates"] is True
    assert plan["emit_candidates_patch"] is not None
    assert plan["shadow_patch"] is not None and plan["rollback_patch"] is not None


def test_full_plan_not_ready_no_emit():
    plan = build_per_channel_stt_canary_plan(_not_ready_report())
    assert plan["status"] == "not_ready"
    assert plan["can_emit_candidates"] is False
    assert plan["emit_candidates_patch"] is None


def test_full_plan_patch_validation_and_safety():
    plan = build_per_channel_stt_canary_plan(_ready_report())
    pv = plan["patch_validation"]
    assert pv["shadow_patch"]["valid"] is True
    assert pv["emit_candidates_patch"]["valid"] is True
    assert pv["rollback_patch"]["valid"] is True
    assert all(plan["safety_checks"].values())
    assert "does_not_contain_api_key" in plan["safety_checks"]  # Этап 19 review: guard присутствует
    assert plan["safety_checks"]["does_not_contain_api_key"] is True


def test_full_plan_no_raw_in_output():
    # реальные raw-форматы значений (имена safety-полей does_not_contain_* — не утечка)
    plan = build_per_channel_stt_canary_plan(_ready_report())
    blob = json.dumps(plan, ensure_ascii=False)
    for raw in ("transcript_text", "SM_1", "track_2", "channel_0", "seg-1", "cand-1", "xi-api-key"):
        assert raw not in blob
    # patch-тела содержат только разрешённые ключи
    for key in (plan["emit_candidates_patch"] or {}):
        assert key.startswith("audio_per_channel_stt_") or key.startswith("source_reconcile_")


# --- CLI ---

def _run(*args):
    return subprocess.run([sys.executable, "-m", "app.core.context.per_channel_stt_canary_operations", *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=_BACKEND)


def _pcs_line(meeting_id="42", **kw):
    base = dict(check_id="c", meeting_id=meeting_id, enabled=True, shadow_mode=True, frame_count=100,
                provider="elevenlabs_batch", segment_finalized_count=10, transcribe_success_count=8,
                candidate_shadow_suppressed_count=8, candidate_emit_count=0, adapter_unavailable_count=0,
                transcribe_timeout_count=0, transcribe_provider_error_count=0,
                transcribe_budget_exhausted_count=0, transcribe_cache_hit_count=2,
                transcribe_cache_miss_count=8, max_channels_seen=2, average_dominance=0.8,
                average_transcribe_latency_ms=1500)
    base.update(kw)
    return "INFO PER_CHANNEL_STT_TRACE " + json.dumps(base)


def test_cli_emit_shadow():
    proc = _run("emit-shadow", "--provider", "elevenlabs_batch")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["shadow_patch"]["audio_per_channel_stt_provider"] == "elevenlabs_batch"
    assert out["endpoint_template"] == "/api/meetings/{meeting_id}/ai-settings"


def test_cli_emit_rollback():
    proc = _run("emit-rollback")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert all(v is None for v in out["rollback_patch"].values())


def test_cli_plan_ready(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_pcs_line() for _ in range(6)), encoding="utf-8")
    proc = _run("plan", str(log), "--meeting-id", "42")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["status"] == "ready"


def test_cli_emit_candidates_ready(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_pcs_line() for _ in range(6)), encoding="utf-8")
    proc = _run("emit-candidates", str(log), "--meeting-id", "42")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["emit_candidates_patch"]["audio_per_channel_stt_shadow_mode"] is False


def test_cli_emit_candidates_not_ready_exit4(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_pcs_line(provider="noop", transcribe_success_count=0,
                                       candidate_shadow_suppressed_count=0, adapter_unavailable_count=10)
                             for _ in range(6)), encoding="utf-8")
    proc = _run("emit-candidates", str(log), "--meeting-id", "42")
    assert proc.returncode == 4
    assert json.loads(proc.stdout)["error"] == "not_ready"


def test_cli_plan_missing_file_exit2():
    assert _run("plan", "no_such.log", "--meeting-id", "42").returncode == 2


def test_cli_invalid_args_exit3():
    assert _run("bogus").returncode == 3
