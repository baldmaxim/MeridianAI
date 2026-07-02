"""Этап 26: privacy evidence report — вердикты + без raw контента."""

import json

from app.core.privacy.privacy_evidence_report import build_privacy_evidence_report


def _safe_smoke(mode="dry_run", **over):
    base = {
        "status": "ok", "mode": mode, "meeting_id_hash": "abc123",
        "inventory_ok": True, "export_ok": True, "delete_plan_ok": True,
        "shared_skipped_count": 1, "blockers": [],
        "safe_checks": {"no_auth_token_in_output": True, "no_confirm_token_in_output": True,
                        "no_base_url_in_output": True, "id_hashed": True},
    }
    base.update(over)
    return base


def test_no_smoke_needs_e2e():
    r = build_privacy_evidence_report(smoke_result=None, privacy_log_summary=None)
    assert r["verdict"] == "needs_staging_privacy_e2e"
    assert "no_privacy_smoke_result" in r["blocking_issues"]


def test_dry_run_ready_for_dry_run_only():
    r = build_privacy_evidence_report(smoke_result=_safe_smoke("dry_run"),
                                      privacy_log_summary={"total": 3})
    assert r["verdict"] == "ready_for_dry_run_only"
    assert r["safe_logging_verified"] is True and r["delete_plan_verified"] is True


def test_execute_ready_for_pilot():
    smoke = _safe_smoke("execute", execution_ok=True, partial_delete=False,
                        post_delete_inventory_ok=True)
    r = build_privacy_evidence_report(smoke_result=smoke, privacy_log_summary={"total": 5},
                                      retention_dry_run_summary={"mode": "dry_run"})
    assert r["verdict"] == "ready_for_privacy_pilot"
    assert r["hard_delete_verified"] is True and r["retention_dry_run_verified"] is True


def test_smoke_not_executed_needs_staging():
    # смок не выполнялся (нет токена) → needs_staging_privacy_e2e, НЕ blocked
    smoke = {"status": "failed", "mode": "dry_run", "blockers": ["auth_token_missing"],
             "safe_checks": {"no_auth_token_in_output": True, "no_confirm_token_in_output": True,
                             "no_base_url_in_output": True, "id_hashed": True}}
    r = build_privacy_evidence_report(smoke_result=smoke, privacy_log_summary=None)
    assert r["verdict"] == "needs_staging_privacy_e2e"
    assert not r["blocking_issues"]


def test_partial_delete_blocked():
    smoke = _safe_smoke("execute", status="partial_delete", execution_ok=True, partial_delete=True)
    r = build_privacy_evidence_report(smoke_result=smoke, privacy_log_summary=None)
    assert r["verdict"] == "blocked" and "partial_delete" in r["blocking_issues"]


def test_unsafe_checks_blocked():
    smoke = _safe_smoke("dry_run")
    smoke["safe_checks"]["no_auth_token_in_output"] = False
    r = build_privacy_evidence_report(smoke_result=smoke, privacy_log_summary=None)
    assert r["verdict"] == "blocked" and "smoke_safe_checks_failed" in r["blocking_issues"]


def test_report_no_raw_content():
    r = build_privacy_evidence_report(smoke_result=_safe_smoke("dry_run"),
                                      privacy_log_summary={"total": 1})
    blob = json.dumps(r, ensure_ascii=False)
    assert r["safe_checks"]["no_raw_content_included"] is True
    # отчёт — только флаги/вердикт/notes, без транскрипта/имён
    assert "transcript text" not in blob and ".pdf" not in blob
