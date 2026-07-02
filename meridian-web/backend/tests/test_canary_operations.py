"""Canary operations toolkit (Этап 13): patches + plan + CLI."""

import json
import subprocess
import sys
from pathlib import Path

from app.core.context.canary_operations import (
    SOURCE_RECONCILE_OVERRIDE_KEYS,
    build_active_source_reconcile_patch,
    build_full_canary_plan,
    build_shadow_collection_patch,
    build_source_reconcile_rollback_patch,
)


def _ready_report():
    return {
        "verdict": "ready_for_active_source_reconcile_canary",
        "blocking_issues": [],
        "warnings": [],
        "suggested_patch": {
            "source_reconcile_enabled": True,
            "source_reconcile_shadow_mode": False,
            "source_reconcile_min_text_similarity": 0.78,
            "source_reconcile_min_time_overlap": 0.45,
            "source_reconcile_min_match_score": 0.9,
            "source_reconcile_ambiguity_margin": 0.08,
        },
    }


def _not_ready_report():
    return {"verdict": "not_ready", "blocking_issues": ["много no_candidates"],
            "warnings": [], "suggested_patch": None}


def test_shadow_patch_validates():
    p = build_shadow_collection_patch()
    assert p["source_reconcile_enabled"] is True
    assert p["source_reconcile_shadow_mode"] is True
    assert p["source_reconcile_trace_enabled"] is True
    from app.services.ai_settings import validate_patch
    validate_patch(p)  # не бросает


def test_shadow_patch_trace_sample_rate_clamped():
    assert build_shadow_collection_patch(trace_sample_rate=5.0)["source_reconcile_trace_sample_rate"] == 1.0
    assert build_shadow_collection_patch(trace_sample_rate=-1)["source_reconcile_trace_sample_rate"] == 0.0


def test_rollback_sets_source_reconcile_to_none():
    p = build_source_reconcile_rollback_patch()
    assert set(p) == set(SOURCE_RECONCILE_OVERRIDE_KEYS)
    assert all(v is None for v in p.values())


def test_rollback_does_not_clear_speaker_identity_hints():
    p = build_source_reconcile_rollback_patch()
    assert "speaker_identity_hints" not in p


def test_rollback_does_not_clear_signal_engine():
    p = build_source_reconcile_rollback_patch()
    assert not any(k.startswith("signal_engine_") for k in p)


def test_active_patch_none_when_not_ready():
    assert build_active_source_reconcile_patch(_not_ready_report()) is None
    assert build_active_source_reconcile_patch({"verdict": "no_data"}) is None
    assert build_active_source_reconcile_patch({"verdict": "active_canary_running"}) is None


def test_active_patch_when_ready():
    p = build_active_source_reconcile_patch(_ready_report())
    assert p is not None
    assert p["source_reconcile_enabled"] is True
    assert p["source_reconcile_shadow_mode"] is False
    assert p["source_reconcile_min_match_score"] == 0.9


def test_active_patch_excludes_speaker_identity_hints():
    rep = _ready_report()
    rep["suggested_patch"]["speaker_identity_hints"] = {"x": "y"}  # должно быть отфильтровано
    p = build_active_source_reconcile_patch(rep)
    assert "speaker_identity_hints" not in p


def test_active_patch_excludes_signal_engine_shadow_mode():
    rep = _ready_report()
    rep["suggested_patch"]["signal_engine_shadow_mode"] = False  # не должно протечь
    p = build_active_source_reconcile_patch(rep)
    assert "signal_engine_shadow_mode" not in p
    assert not any(k.startswith("signal_engine_") for k in p)


def test_full_plan_ready_can_apply_active():
    plan = build_full_canary_plan(_ready_report())
    assert plan["status"] == "ready"
    assert plan["can_apply_active_patch"] is True
    assert plan["active_source_reconcile_patch"] is not None
    assert plan["shadow_collection_patch"] is not None
    assert plan["rollback_patch"] is not None


def test_full_plan_not_ready_active_none():
    plan = build_full_canary_plan(_not_ready_report())
    assert plan["status"] == "not_ready"
    assert plan["can_apply_active_patch"] is False
    assert plan["active_source_reconcile_patch"] is None


def test_full_plan_patch_validation_valid():
    plan = build_full_canary_plan(_ready_report())
    pv = plan["patch_validation"]
    assert pv["shadow_collection_patch"]["valid"] is True
    assert pv["active_source_reconcile_patch"]["valid"] is True
    assert pv["rollback_patch"]["valid"] is True


def test_full_plan_safety_checks_all_true():
    plan = build_full_canary_plan(_ready_report())
    assert all(plan["safety_checks"].values())


def test_full_plan_no_raw_in_output():
    # план не должен содержать raw values (форматы реальных labels/source/segment ids).
    # Описательные имена safety-полей (does_not_contain_raw_speaker_labels) — не утечка.
    plan = build_full_canary_plan(_ready_report())
    blob = json.dumps(plan, ensure_ascii=False)
    for raw in ("SM_1", "SM_2", "track_2", "primary", "secondary",
                "seg-1", "cand-1", "Speaker SM", "transcript_text"):
        assert raw not in blob
    # patch-тела содержат только source_reconcile_* ключи
    for key in (plan["active_source_reconcile_patch"] or {}):
        assert key.startswith("source_reconcile_")


def test_full_plan_endpoint_is_placeholder():
    plan = build_full_canary_plan(_ready_report())
    assert plan["endpoint_template"] == "/api/meetings/{meeting_id}/ai-settings"
    assert "{meeting_id}" in plan["endpoint_template"]  # не подставлен реальный id


# --- CLI ---

_BACKEND = str(Path(__file__).resolve().parents[1])


def _sr_line(meeting_id="42", **kw):
    base = dict(would_attach_without_shadow=True, actual_attach=False, decision_reason="shadow_mode",
                match_reason="matched", match_score=0.9, time_overlap=1.0, text_similarity=1.0,
                attribution_confidence=0.85, candidate_source="multi_channel_live",
                source_kind="multi_channel", attribution_source="multi_source_segment",
                meeting_id=meeting_id, check_id="chk")
    base.update(kw)
    return "INFO SOURCE_RECONCILE_TRACE " + json.dumps(base)


def _run(*args):
    return subprocess.run([sys.executable, "-m", "app.core.context.canary_operations", *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=_BACKEND)


def test_cli_emit_shadow():
    proc = _run("emit-shadow")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["shadow_collection_patch"]["source_reconcile_shadow_mode"] is True


def test_cli_emit_rollback():
    proc = _run("emit-rollback")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert all(v is None for v in out["rollback_patch"].values())


def test_cli_plan(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_sr_line() for _ in range(10)), encoding="utf-8")
    proc = _run("plan", str(log), "--meeting-id", "42")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["status"] == "ready"
    assert out["can_apply_active_patch"] is True
    # no raw ids in output
    assert "42" not in json.dumps(out.get("trace_filters", {}).get("filter_hashes", {}))


def test_cli_emit_active_ready(tmp_path: Path):
    log = tmp_path / "app.log"
    log.write_text("\n".join(_sr_line() for _ in range(10)), encoding="utf-8")
    proc = _run("emit-active", str(log), "--meeting-id", "42")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["active_source_reconcile_patch"]["source_reconcile_shadow_mode"] is False


def test_cli_emit_active_not_ready_exit4(tmp_path: Path):
    log = tmp_path / "app.log"
    line = _sr_line(would_attach_without_shadow=False, match_reason="no_candidates",
                    decision_reason="no_candidates", match_score=0.0)
    log.write_text("\n".join(line for _ in range(10)), encoding="utf-8")
    proc = _run("emit-active", str(log), "--meeting-id", "42")
    assert proc.returncode == 4
    out = json.loads(proc.stdout)
    assert out["error"] == "not_ready"


def test_cli_missing_file_exit2():
    proc = _run("plan", "no_such_file.log", "--meeting-id", "42")
    assert proc.returncode == 2


def test_cli_invalid_args_exit3():
    proc = _run("bogus-command")
    assert proc.returncode == 3


def test_cli_monitor_subcommand(tmp_path: Path):
    # Этап 14: operations CLI делегирует monitor в active_canary_monitor
    log = tmp_path / "app.log"
    lines = [_sr_line(meeting_id="42").replace('"actual_attach": false', '"actual_attach": true')
             for _ in range(3)]
    lines += [_sr_line(meeting_id="42") for _ in range(9)]  # would, not actual
    log.write_text("\n".join(lines), encoding="utf-8")
    proc = _run("monitor", str(log), "--meeting-id", "42")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert "status" in out and "primary_recommendation" in out
    assert out["active_state"] == "active_attaching"
