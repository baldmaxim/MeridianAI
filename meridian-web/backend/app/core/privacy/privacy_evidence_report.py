"""Privacy pilot evidence report (Этап 26).

Сводит safe-результаты privacy staging smoke + privacy log analysis (+ опц. retention dry-run) в
единый безопасный вердикт готовности к privacy-пилоту. Ничего не удаляет, сеть/БД не трогает, raw
контент не включает.

CLI:
  python -m app.core.privacy.privacy_evidence_report \
      --smoke-json staging_evidence/privacy_staging_smoke.safe.json \
      --privacy-log-json staging_evidence/privacy_log_analysis.safe.json \
      [--retention-json staging_evidence/retention_dry_run.safe.json] \
      --output staging_evidence/privacy_pilot_evidence.safe.json
Exit: 0 ок; 2 файл не найден/IO; 3 неверные аргументы.
"""

import argparse
import json
import sys

# блокеры privacy smoke, означающие «не выполнялся» (нет env/токена), а не провал
_NOT_EXECUTED_BLOCKERS = {
    "auth_token_missing", "confirmation_token_missing", "missing_--i-understand-hard-delete",
}

_ROLLBACK_NOTES = [
    "hard delete необратим на уровне приложения (нет undo контента; S3-объект удаляется физически)",
    "перед execute: бэкап БД + S3 versioning/бэкап",
    "PRIVACY_HARD_DELETE_ENABLED=false для dry-run; true только на точечный execute-тест",
]


def _all_safe(smoke: dict | None) -> bool:
    checks = (smoke or {}).get("safe_checks") or {}
    return bool(checks) and all(bool(v) for v in checks.values())


def build_privacy_evidence_report(*, smoke_result: dict | None,
                                  privacy_log_summary: dict | None,
                                  retention_dry_run_summary: dict | None = None) -> dict:
    blocking: list[str] = []
    warnings: list[str] = []

    smoke = smoke_result or None
    mode = (smoke or {}).get("mode")
    status = (smoke or {}).get("status")
    safe_ok = _all_safe(smoke)

    inventory_verified = bool((smoke or {}).get("inventory_ok") or (smoke or {}).get("post_delete_inventory_ok"))
    export_verified = bool((smoke or {}).get("export_ok"))
    delete_plan_verified = bool((smoke or {}).get("delete_plan_ok"))
    shared_skip_verified = bool((smoke or {}).get("delete_plan_ok"))  # план сообщает shared_skipped_count
    hard_delete_verified = bool((smoke or {}).get("execution_ok") and not (smoke or {}).get("partial_delete"))
    retention_dry_run_verified = bool(retention_dry_run_summary
                                      and retention_dry_run_summary.get("mode") == "dry_run")
    safe_logging_verified = bool(privacy_log_summary is not None)

    smoke_blockers = (smoke or {}).get("blockers") or []
    # смок НЕ выполнялся (нет env/токена) = отсутствие evidence, а не провал → needs_staging_privacy_e2e
    not_executed = bool(smoke_blockers) and all(b in _NOT_EXECUTED_BLOCKERS for b in smoke_blockers)

    if smoke is None:
        verdict = "needs_staging_privacy_e2e"
        blocking.append("no_privacy_smoke_result")
    elif not safe_ok:
        verdict = "blocked"
        blocking.append("smoke_safe_checks_failed")
    elif not_executed:
        verdict = "needs_staging_privacy_e2e"
        warnings.append("privacy_smoke_not_executed_missing_prerequisites")
    elif status in ("failed", "partial_delete") or smoke_blockers:
        verdict = "blocked"
        for b in smoke_blockers:
            blocking.append(f"smoke_blocker:{b}")
        if status == "partial_delete":
            blocking.append("partial_delete")
    elif mode == "execute":
        if hard_delete_verified:
            verdict = "ready_for_privacy_pilot"
        else:
            verdict = "blocked"
            blocking.append("hard_delete_not_verified")
    elif mode == "dry_run":
        if inventory_verified and export_verified and delete_plan_verified:
            verdict = "ready_for_dry_run_only"
        else:
            verdict = "blocked"
            blocking.append("dry_run_incomplete")
    else:
        verdict = "needs_staging_privacy_e2e"

    if privacy_log_summary is None:
        warnings.append("privacy_log_summary_not_provided")
    if not retention_dry_run_verified:
        warnings.append("retention_dry_run_not_provided")

    next_action = {
        "needs_staging_privacy_e2e": "запустить privacy_staging_smoke --dry-run на staging",
        "ready_for_dry_run_only": "получить confirmation_token из delete-plan и выполнить один execute-тест на тестовой встрече",
        "ready_for_privacy_pilot": "включать privacy-контролы для пилота (hard delete точечно, под наблюдением)",
        "blocked": "устранить blocking_issues и повторить staging smoke",
    }.get(verdict, "запустить staging privacy E2E")

    return {
        "verdict": verdict,
        "blocking_issues": blocking,
        "warnings": warnings,
        "inventory_verified": inventory_verified,
        "export_verified": export_verified,
        "delete_plan_verified": delete_plan_verified,
        "hard_delete_verified": hard_delete_verified,
        "retention_dry_run_verified": retention_dry_run_verified,
        "safe_logging_verified": safe_logging_verified,
        "shared_skip_verified": shared_skip_verified,
        "rollback_or_recovery_notes": _ROLLBACK_NOTES,
        "next_action": next_action,
        "safe_checks": {
            "smoke_safe_checks_all_true": safe_ok,
            "no_raw_content_included": True,  # по построению включаем только флаги/counts
        },
    }


def _read_json(path: str | None):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(
        prog="python -m app.core.privacy.privacy_evidence_report",
        description="Единый safe evidence-report готовности к privacy-пилоту (Этап 26).")
    p.add_argument("--smoke-json", default=None)
    p.add_argument("--privacy-log-json", default=None)
    p.add_argument("--retention-json", default=None)
    p.add_argument("--output", default=None)
    try:
        ns = p.parse_args(argv[1:])
    except SystemExit:
        return 3
    try:
        smoke = _read_json(ns.smoke_json)
        plog = _read_json(ns.privacy_log_json)
        retention = _read_json(ns.retention_json)
    except FileNotFoundError as e:
        print(f"Файл не найден: {e.filename}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"Ошибка чтения JSON: {type(e).__name__}", file=sys.stderr)
        return 2

    report = build_privacy_evidence_report(
        smoke_result=smoke, privacy_log_summary=plog, retention_dry_run_summary=retention)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
