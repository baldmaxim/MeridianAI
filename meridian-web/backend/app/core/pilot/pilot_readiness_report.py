"""Limited pilot readiness aggregator (Этап 27).

Backend-only операторский слой: объединяет уже собранные safe evidence-артефакты (document staging
smoke + log analysis, privacy evidence, field canary, config audit, test evidence) в единый вердикт
готовности к limited pilot + rollback-матрицу. Не ходит в сеть/БД, не применяет PATCH, не включает
canary. Вывод — только statuses/counts/booleans/categories; никаких raw text/audio/S3 key/URL/token.

CLI:
  python -m app.core.pilot.pilot_readiness_report \
      --document-smoke staging_evidence/document_upload_smoke.safe.json \
      --document-log staging_evidence/document_upload_log_analysis.safe.json \
      --privacy-evidence staging_evidence/privacy_pilot_evidence.safe.json \
      --field-canary staging_evidence/field_canary_report.safe.json \
      --tests-json staging_evidence/test_evidence.safe.json \
      [--include-config-audit] [--strict] [--allow-internal-pilot-without-staging-e2e] \
      --output staging_evidence/limited_pilot_readiness.safe.json
Exit: 0 ready_*; 2 required file missing; 3 неверные аргументы; 4 blocked/needs_evidence при --strict.
"""

import argparse
import json
import sys

_ROLLBACK_MATRIX = {
    "document_upload": ["set DOCUMENT_S3_UPLOAD_ENABLED=false → фронт уходит на legacy multipart (без деплоя)"],
    "source_reconcile": ["source_reconcile_* → null на встрече; глобальный AI_SOURCE_RECONCILE_SHADOW_MODE=true"],
    "per_channel_stt": ["audio_per_channel_stt_* → null; AI_AUDIO_PER_CHANNEL_STT_ENABLED=false / SHADOW_MODE=true"],
    "privacy_delete": ["PRIVACY_HARD_DELETE_ENABLED=false; восстановление только из бэкапа БД / S3 versioning (необратимо на уровне app)"],
    "signal_engine": ["AI_SIGNAL_ENGINE_SHADOW_MODE=true (или AI_SIGNAL_ENGINE_ENABLED=false)"],
}


def load_json_file_safe(path: str) -> dict | None:
    """Прочитать JSON. Нет файла → None; битый JSON/IO → safe error-объект (без raw content)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"_error": "not_a_json_object"}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"_error": "invalid_or_unreadable_json"}


def _all_true(d) -> bool:
    return isinstance(d, dict) and bool(d) and all(bool(v) for v in d.values())


def _safe_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _analyze_documents(document_evidence, document_log_analysis) -> dict:
    de = document_evidence or {}
    dla = document_log_analysis or {}
    out = {"evaluated": document_evidence is not None, "upload_e2e_ok": None,
           "processing_ready": None, "safe_logging_ok": None,
           "legacy_fallback_only": False, "blockers": []}
    if not out["evaluated"]:
        return out
    if de.get("_error"):
        out["blockers"].append("document_evidence_unreadable")
        return out
    executed = de.get("network_smoke_executed")
    status = de.get("status")
    mode = de.get("upload_mode")
    out["legacy_fallback_only"] = mode == "legacy_multipart"
    # E2E засчитываем только при ЯВНОМ network_smoke_executed=True. None/False = НЕ выполнялось
    # (missing env) — это ОТСУТСТВИЕ evidence, а не провал → не hard-blocker; upload_e2e_ok
    # остаётся None и вердикт склоняется к needs_evidence, а не blocked.
    if executed is not True:
        return out
    out["upload_e2e_ok"] = bool(status == "ok" and de.get("initiate_ok")
                                and de.get("put_ok") and de.get("confirm_ok"))
    out["processing_ready"] = de.get("processing_status") == "ready"
    # safe logging: из safe_checks smoke + (при наличии) log-analysis без «сырья» (он safe by construction)
    sc = de.get("safe_checks") or {}
    out["safe_logging_ok"] = _all_true(sc) if sc else (dla is not None and not dla.get("_error"))
    if status == "failed":
        out["blockers"].append("document_upload_failed")
    if de.get("processing_status") == "error":
        out["blockers"].append("document_processing_error")
    if sc and not _all_true(sc):
        out["blockers"].append("document_smoke_safe_checks_failed")
    return out


def _analyze_privacy(privacy_evidence) -> dict:
    pe = privacy_evidence or {}
    out = {"evaluated": privacy_evidence is not None, "dry_run_ok": None,
           "hard_delete_verified": None, "safe_logging_ok": None,
           "retention_dry_run_ok": None, "blockers": []}
    if not out["evaluated"]:
        return out
    if pe.get("_error"):
        out["blockers"].append("privacy_evidence_unreadable")
        return out
    out["dry_run_ok"] = bool(pe.get("inventory_verified") and pe.get("export_verified")
                             and pe.get("delete_plan_verified"))
    out["hard_delete_verified"] = bool(pe.get("hard_delete_verified"))
    out["safe_logging_ok"] = bool(pe.get("safe_logging_verified")
                                  or (pe.get("safe_checks") or {}).get("no_raw_content_included"))
    out["retention_dry_run_ok"] = bool(pe.get("retention_dry_run_verified"))
    if pe.get("verdict") == "blocked":
        out["blockers"].append("privacy_evidence_blocked")
    scs = pe.get("safe_checks") or {}
    if scs and not scs.get("smoke_safe_checks_all_true", True):
        out["blockers"].append("privacy_unsafe_checks")
    return out


def _analyze_audio_canary(field_canary_report, config_audit) -> dict:
    fc = field_canary_report or {}
    ca = config_audit or {}
    per_channel_active = bool((ca.get("summary") or {}).get("per_channel_stt_enabled")
                              and not (ca.get("summary") or {}).get("per_channel_stt_shadow", True))
    out = {"evaluated": field_canary_report is not None, "status": None, "recommendation": None,
           "requires_operator_canary": per_channel_active, "blockers": [], "warnings": []}
    if not out["evaluated"]:
        if per_channel_active:
            out["blockers"].append("per_channel_active_but_no_canary_evidence")
        return out
    if fc.get("_error"):
        out["blockers"].append("field_canary_unreadable")
        return out
    out["status"] = fc.get("status")
    out["recommendation"] = fc.get("primary_recommendation") or fc.get("recommendation")
    safety = fc.get("safety_checks") or {}
    if safety and not _all_true(safety):
        out["blockers"].append("field_canary_safety_checks_failed")
    if out["status"] == "rollback_recommended":
        out["warnings"].append("field_canary_rollback_recommended")
    return out


def _analyze_tests(test_evidence) -> dict:
    te = test_evidence or {}
    out = {"evaluated": test_evidence is not None, "backend_green": None,
           "frontend_green": None, "known_failures": []}
    if not out["evaluated"]:
        return out
    if te.get("_error"):
        out["known_failures"].append("test_evidence_unreadable")
        return out
    be = te.get("backend") if isinstance(te.get("backend"), dict) else {}
    out["backend_green"] = bool(_safe_int(be.get("passed")) > 0 and _safe_int(be.get("failed")) == 0)
    fe = te.get("frontend") if isinstance(te.get("frontend"), dict) else {}
    if "build" in fe:
        out["frontend_green"] = fe.get("build") == "passed"
    out["known_failures"] = list(te.get("known_failures") or [])
    return out


def _pilot_scope(verdict: str, documents: dict) -> dict:
    max_meetings = {"ready_for_limited_pilot": 10, "ready_for_internal_pilot": 5}.get(verdict, 0)
    allowed = ["realtime_transcription", "live_suggestions", "meeting_finalization"]
    if documents.get("upload_e2e_ok"):
        allowed.append("document_upload_s3")
    return {
        "max_meetings": max_meetings,
        "allowed_features": allowed,
        "must_remain_shadow": ["signal_engine", "source_reconcile"],
        "must_remain_disabled": ["per_channel_stt_active", "privacy_hard_delete", "retention_cleanup"],
    }


# bare-токены (без кавычек/двоеточий) — переживают JSON-escaping вложенных строк. Произвольную прозу
# транскрипта substring-ом не поймать; ловим утёкшие имена полей/структур transcript-контента.
_TEXT_MARKERS = ("raw_text", "transcript_text", "committed_segment", "segment_text", "words_json")
_AUDIO_MARKERS = ("riff", "id3", "data:audio", "wav_bytes", "pcm16")
_S3_MARKERS = ("meridian/", "s3://")
_URL_MARKERS = ("http://", "https://", "x-amz-signature", "x-amz-credential", "presigned")
_APIKEY_MARKERS = ("sk_live", "sk_test", "pk_live", "rk_live", "akia", "asia",
                   "bearer ", "xi-api-key", "-----begin")
_SPEAKER_MARKERS = ("speaker_label", "sm_0", "sm_1", "speaker 1", "speaker_1")


def _safety_checks(report_blob: str) -> dict:
    """Реально сканирует сериализованный отчёт на запрещённые маркеры (агрегатор копирует только
    safe-поля, но это защитный слой на случай мусорного/вредоносного evidence)."""
    low = report_blob.lower()

    def _clean(markers):
        return not any(m in low for m in markers)

    return {
        "does_not_contain_raw_text": _clean(_TEXT_MARKERS),
        "does_not_contain_raw_audio": _clean(_AUDIO_MARKERS),
        "does_not_contain_s3_key": _clean(_S3_MARKERS),
        "does_not_contain_presigned_url": _clean(_URL_MARKERS),
        "does_not_contain_api_keys": _clean(_APIKEY_MARKERS),
        "does_not_contain_speaker_labels": _clean(_SPEAKER_MARKERS),
    }


def analyze_pilot_readiness(*, document_evidence: dict | None = None,
                            document_log_analysis: dict | None = None,
                            privacy_evidence: dict | None = None,
                            field_canary_report: dict | None = None,
                            config_audit: dict | None = None,
                            test_evidence: dict | None = None,
                            allow_internal_pilot: bool = False) -> dict:
    documents = _analyze_documents(document_evidence, document_log_analysis)
    privacy = _analyze_privacy(privacy_evidence)
    audio = _analyze_audio_canary(field_canary_report, config_audit)
    tests = _analyze_tests(test_evidence)

    config_safety = {"evaluated": config_audit is not None, "safe_defaults_ok": None,
                     "dangerous_flags": [], "warnings": []}
    if config_audit is not None and not config_audit.get("_error"):
        config_safety["safe_defaults_ok"] = bool(config_audit.get("safe_defaults_ok"))
        config_safety["dangerous_flags"] = list(config_audit.get("dangerous_flags") or [])
        config_safety["warnings"] = list(config_audit.get("warnings") or [])

    blocking: list[str] = []
    warnings: list[str] = []
    blocking += [f"documents:{b}" for b in documents["blockers"]]
    blocking += [f"privacy:{b}" for b in privacy["blockers"]]
    blocking += [f"audio_canary:{b}" for b in audio["blockers"]]
    warnings += [f"audio_canary:{w}" for w in audio["warnings"]]
    blocking += [f"config:{f}" for f in config_safety["dangerous_flags"]]
    warnings += [f"config:{w}" for w in config_safety["warnings"]]
    if tests["evaluated"]:
        if tests["backend_green"] is False:
            blocking.append("tests:backend_failed")
        if tests["frontend_green"] is False:
            blocking.append("tests:frontend_failed")

    # достаточно ли staging-доказательств для limited pilot
    docs_ok = bool(documents.get("upload_e2e_ok") and documents.get("processing_ready")
                   and documents.get("safe_logging_ok"))
    privacy_ok = bool(privacy.get("dry_run_ok") and privacy.get("safe_logging_ok"))
    tests_green = bool(tests.get("backend_green") and (tests.get("frontend_green") in (True, None)))
    # limited pilot требует ЯВНО пройденного config audit (safe_defaults_ok True); internal — лишь
    # отсутствие опасных флагов (None допустим, если аудит не прогоняли).
    config_audited_safe = config_safety["safe_defaults_ok"] is True
    config_not_dangerous = config_safety["safe_defaults_ok"] in (True, None)

    if blocking:
        verdict = "blocked"
        next_action = "устранить blocking_issues и пересобрать evidence"
    elif (documents["evaluated"] and privacy["evaluated"] and docs_ok and privacy_ok
          and tests_green and config_audited_safe):
        verdict = "ready_for_limited_pilot"
        next_action = "запускать limited pilot по pilot_scope_recommendation, под наблюдением + rollback наготове"
    elif tests_green and config_not_dangerous and allow_internal_pilot:
        verdict = "ready_for_internal_pilot"
        next_action = "внутренний (не клиентский) пилот; выполнить staging E2E документов/privacy перед limited pilot"
        if not (documents["evaluated"] and privacy["evaluated"]):
            warnings.append("staging_e2e_evidence_missing")
    else:
        verdict = "needs_evidence"
        next_action = "собрать document staging E2E + privacy dry-run evidence + прогнать тесты"

    report = {
        "verdict": verdict,
        "blocking_issues": blocking,
        "warnings": warnings,
        "recommended_next_action": next_action,
        "documents": documents,
        "privacy": privacy,
        "audio_canary": audio,
        "config_safety": config_safety,
        "tests": tests,
        "pilot_scope_recommendation": _pilot_scope(verdict, documents),
        "rollback_matrix": _ROLLBACK_MATRIX,
    }
    report["safety_checks"] = _safety_checks(json.dumps(report, ensure_ascii=False))
    return report


def _main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(
        prog="python -m app.core.pilot.pilot_readiness_report",
        description="Единый safe-вердикт готовности к limited pilot (Этап 27).")
    p.add_argument("--document-smoke", default=None)
    p.add_argument("--document-log", default=None)
    p.add_argument("--privacy-evidence", default=None)
    p.add_argument("--field-canary", default=None)
    p.add_argument("--tests-json", default=None)
    p.add_argument("--config-audit-json", default=None)
    p.add_argument("--include-config-audit", action="store_true")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--allow-internal-pilot-without-staging-e2e", action="store_true")
    p.add_argument("--output", default=None)
    try:
        ns = p.parse_args(argv[1:])
    except SystemExit:
        return 3

    config_audit = load_json_file_safe(ns.config_audit_json) if ns.config_audit_json else None
    if config_audit is None and ns.include_config_audit:
        from .pilot_config_audit import build_pilot_config_audit
        from ...config import get_settings
        config_audit = build_pilot_config_audit(get_settings())

    report = analyze_pilot_readiness(
        document_evidence=load_json_file_safe(ns.document_smoke) if ns.document_smoke else None,
        document_log_analysis=load_json_file_safe(ns.document_log) if ns.document_log else None,
        privacy_evidence=load_json_file_safe(ns.privacy_evidence) if ns.privacy_evidence else None,
        field_canary_report=load_json_file_safe(ns.field_canary) if ns.field_canary else None,
        config_audit=config_audit,
        test_evidence=load_json_file_safe(ns.tests_json) if ns.tests_json else None,
        allow_internal_pilot=ns.allow_internal_pilot_without_staging_e2e,
    )

    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if ns.output:
        try:
            with open(ns.output, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            print(f"Ошибка записи: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"written": ns.output, "verdict": report["verdict"]}, ensure_ascii=False))
    else:
        print(blob)

    if ns.strict and report["verdict"] in ("blocked", "needs_evidence"):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
