"""Этап 27: pilot readiness aggregator — вердикты, rollback-матрица, safety checks."""

import json

from app.core.pilot import pilot_readiness_report as prr
from app.core.pilot.pilot_readiness_report import analyze_pilot_readiness


def _doc_ok():
    return {"network_smoke_executed": True, "status": "ok", "upload_mode": "s3_presigned",
            "initiate_ok": True, "put_ok": True, "confirm_ok": True, "processing_status": "ready",
            "safe_checks": {"no_token_in_output": True, "id_hashed": True}}


def _priv_ok():
    return {"verdict": "ready_for_dry_run_only", "inventory_verified": True, "export_verified": True,
            "delete_plan_verified": True, "hard_delete_verified": False,
            "retention_dry_run_verified": True, "safe_logging_verified": True,
            "safe_checks": {"smoke_safe_checks_all_true": True, "no_raw_content_included": True}}


def _tests_ok():
    return {"backend": {"passed": 1197, "failed": 0}, "frontend": {"build": "passed"}, "known_failures": []}


def _config_ok():
    return {"safe_defaults_ok": True, "dangerous_flags": [], "warnings": [], "summary": {}}


def test_no_evidence_needs_evidence():
    r = analyze_pilot_readiness()
    assert r["verdict"] == "needs_evidence"
    assert r["documents"]["evaluated"] is False and r["privacy"]["evaluated"] is False


def test_document_failed_blocked():
    de = _doc_ok(); de["status"] = "failed"; de["put_ok"] = False
    r = analyze_pilot_readiness(document_evidence=de, privacy_evidence=_priv_ok(),
                                test_evidence=_tests_ok(), config_audit=_config_ok())
    assert r["verdict"] == "blocked"
    assert any("document" in b for b in r["blocking_issues"])


def test_privacy_blocked():
    pe = _priv_ok(); pe["verdict"] = "blocked"
    r = analyze_pilot_readiness(document_evidence=_doc_ok(), privacy_evidence=pe,
                                test_evidence=_tests_ok(), config_audit=_config_ok())
    assert r["verdict"] == "blocked" and any("privacy" in b for b in r["blocking_issues"])


def test_tests_failed_blocked():
    te = _tests_ok(); te["backend"] = {"passed": 1000, "failed": 3}
    r = analyze_pilot_readiness(document_evidence=_doc_ok(), privacy_evidence=_priv_ok(),
                                test_evidence=te, config_audit=_config_ok())
    assert r["verdict"] == "blocked" and "tests:backend_failed" in r["blocking_issues"]


def test_dangerous_config_blocked():
    ca = _config_ok(); ca["safe_defaults_ok"] = False; ca["dangerous_flags"] = ["privacy_hard_delete_enabled"]
    r = analyze_pilot_readiness(document_evidence=_doc_ok(), privacy_evidence=_priv_ok(),
                                test_evidence=_tests_ok(), config_audit=ca)
    assert r["verdict"] == "blocked" and "config:privacy_hard_delete_enabled" in r["blocking_issues"]


def test_all_ok_ready_for_limited_pilot():
    r = analyze_pilot_readiness(document_evidence=_doc_ok(), privacy_evidence=_priv_ok(),
                                test_evidence=_tests_ok(), config_audit=_config_ok())
    assert r["verdict"] == "ready_for_limited_pilot"
    assert r["pilot_scope_recommendation"]["max_meetings"] == 10
    assert "document_upload_s3" in r["pilot_scope_recommendation"]["allowed_features"]
    assert "signal_engine" in r["pilot_scope_recommendation"]["must_remain_shadow"]


def test_internal_pilot_when_allowed_and_no_staging():
    r = analyze_pilot_readiness(test_evidence=_tests_ok(), config_audit=_config_ok(),
                                allow_internal_pilot=True)
    assert r["verdict"] == "ready_for_internal_pilot"
    assert "staging_e2e_evidence_missing" in r["warnings"]


def test_internal_pilot_not_allowed_without_flag():
    r = analyze_pilot_readiness(test_evidence=_tests_ok(), config_audit=_config_ok(),
                                allow_internal_pilot=False)
    assert r["verdict"] == "needs_evidence"


def test_limited_pilot_requires_config_audit():
    # без config audit (None) полный doc/privacy/tests не даёт ready_for_limited_pilot
    r = analyze_pilot_readiness(document_evidence=_doc_ok(), privacy_evidence=_priv_ok(),
                                test_evidence=_tests_ok(), config_audit=None)
    assert r["verdict"] != "ready_for_limited_pilot"


def test_rollback_matrix_present():
    r = analyze_pilot_readiness(document_evidence=_doc_ok(), privacy_evidence=_priv_ok(),
                                test_evidence=_tests_ok(), config_audit=_config_ok())
    for key in ("document_upload", "source_reconcile", "per_channel_stt", "privacy_delete", "signal_engine"):
        assert key in r["rollback_matrix"] and r["rollback_matrix"][key]


def test_safety_checks_catch_forbidden_url():
    # если извлекаемое поле (recommendation) содержит presigned URL — safety check ловит это
    fc = {"status": "healthy", "recommendation": "https://bucket.s3/x?X-Amz-Signature=LEAK",
          "safety_checks": {"ok": True}}
    r = analyze_pilot_readiness(document_evidence=_doc_ok(), privacy_evidence=_priv_ok(),
                                test_evidence=_tests_ok(), config_audit=_config_ok(),
                                field_canary_report=fc)
    assert r["safety_checks"]["does_not_contain_presigned_url"] is False


def test_safety_checks_clean_by_default():
    r = analyze_pilot_readiness(document_evidence=_doc_ok(), privacy_evidence=_priv_ok(),
                                test_evidence=_tests_ok(), config_audit=_config_ok())
    assert all(r["safety_checks"].values())


def test_malformed_evidence_no_crash():
    # non-dict safe_checks, non-numeric test counts, _error объекты → не падает
    de = {"network_smoke_executed": True, "status": "ok", "initiate_ok": True, "put_ok": True,
          "confirm_ok": True, "processing_status": "ready", "safe_checks": "not-a-dict"}
    te = {"backend": {"passed": "abc", "failed": None}, "frontend": "nope"}
    r = analyze_pilot_readiness(document_evidence=de,
                                privacy_evidence={"_error": "invalid_or_unreadable_json"},
                                test_evidence=te, config_audit={"_error": "invalid"})
    assert r["verdict"] in ("blocked", "needs_evidence")
    assert r["tests"]["backend_green"] is False  # non-numeric passed → 0


def test_document_not_executed_is_needs_evidence_not_blocked():
    # not-executed = отсутствие evidence, НЕ провал: upload_e2e_ok=None, не hard-blocker,
    # вердикт склоняется к needs_evidence (не blocked / не limited).
    de = _doc_ok(); de["network_smoke_executed"] = False
    r = analyze_pilot_readiness(document_evidence=de, privacy_evidence=_priv_ok(),
                                test_evidence=_tests_ok(), config_audit=_config_ok())
    assert r["verdict"] == "needs_evidence"
    assert r["documents"]["upload_e2e_ok"] is None
    assert not any("not_executed" in b for b in r["blocking_issues"])


def test_safety_checks_catch_raw_text_and_speaker():
    # утёкшие имена полей transcript-контента + speaker label в извлекаемом поле
    fc = {"status": "healthy", "recommendation": "leaked transcript_text and speaker_label SM_0",
          "safety_checks": {"ok": True}}
    r = analyze_pilot_readiness(field_canary_report=fc, test_evidence=_tests_ok(),
                                config_audit=_config_ok())
    assert r["safety_checks"]["does_not_contain_raw_text"] is False
    assert r["safety_checks"]["does_not_contain_speaker_labels"] is False


def test_cli_writes_output(tmp_path):
    tj = tmp_path / "tests.json"
    tj.write_text(json.dumps(_tests_ok()), encoding="utf-8")
    out = tmp_path / "readiness.safe.json"
    code = prr._main(["prog", "--tests-json", str(tj), "--allow-internal-pilot-without-staging-e2e",
                      "--output", str(out)])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["verdict"] == "ready_for_internal_pilot"


def test_cli_strict_blocked_exit_4(tmp_path):
    tj = tmp_path / "tests.json"
    tj.write_text(json.dumps({"backend": {"passed": 1, "failed": 5}}), encoding="utf-8")
    code = prr._main(["prog", "--tests-json", str(tj), "--strict"])
    assert code == 4
