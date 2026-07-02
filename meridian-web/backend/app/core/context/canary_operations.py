"""Canary Operations Toolkit (Этап 13).

Backend-only генератор безопасного operational plan и PATCH JSON для запуска source_reconcile
canary на ОДНОЙ встрече. Tool НЕ применяет patch, НЕ ходит в сеть, НЕ читает БД, НЕ включает
Signal Engine active mode, НЕ трогает speaker_identity_hints.

Patch'и предназначены для ручного применения через `PATCH /api/meetings/{meeting_id}/ai-settings`.
Вывод — только агрегаты/флаги: никакого raw text / source ids / speaker labels / segment ids.
"""

import argparse
import json
import sys
from typing import Optional

from .canary_readiness_analysis import (
    analyze_canary_readiness_from_events,
    extract_all_canary_trace_events_from_lines,
)

# Скрытые per-meeting override-ключи source_reconcile (зеркало ai_settings._RECONCILE_*).
# Только эти ключи допустимы в canary-patch; ничего из speaker_identity_hints/signal_engine_*.
SOURCE_RECONCILE_OVERRIDE_KEYS = [
    "source_reconcile_enabled",
    "source_reconcile_shadow_mode",
    "source_reconcile_trace_enabled",
    "source_reconcile_trace_sample_rate",
    "source_reconcile_min_candidate_confidence",
    "source_reconcile_min_time_overlap",
    "source_reconcile_min_text_similarity",
    "source_reconcile_min_match_score",
    "source_reconcile_ambiguity_margin",
    "source_reconcile_max_candidates",
    "source_reconcile_max_age_ms",
]

# Ключи, которые canary-tool НИКОГДА не должен включать в patch (защита от расширения охвата).
_FORBIDDEN_PATCH_KEYS = {"speaker_identity_hints"}

ENDPOINT_TEMPLATE = "/api/meetings/{meeting_id}/ai-settings"

# Грубый guard: эти подстроки не должны встречаться в сериализованном plan.
_FORBIDDEN_RAW_TOKENS = (
    "transcript", "speaker_label", "audio_source_id", "channel_label",
    "segment_id", "candidate_id", "SM_", "Speaker ",
)


def build_shadow_collection_patch(*, trace_sample_rate: Optional[float] = None) -> dict:
    """Patch для безопасного сбора shadow-данных: reconcile включён, attach НЕ происходит."""
    patch = {
        "source_reconcile_enabled": True,
        "source_reconcile_shadow_mode": True,
        "source_reconcile_trace_enabled": True,
    }
    if trace_sample_rate is not None:
        patch["source_reconcile_trace_sample_rate"] = max(0.0, min(1.0, float(trace_sample_rate)))
    return patch


def build_active_source_reconcile_patch(readiness_report: dict) -> Optional[dict]:
    """Patch для active canary на ОДНОЙ встрече. None, если readiness не ready.

    Берёт suggested_patch из readiness_report, форсит enabled=true/shadow=false и оставляет ТОЛЬКО
    source_reconcile_* ключи (никаких speaker_identity_hints / signal_engine_*).
    """
    if not isinstance(readiness_report, dict):
        return None
    if readiness_report.get("verdict") != "ready_for_active_source_reconcile_canary":
        return None
    suggested = readiness_report.get("suggested_patch") or {}
    patch = {k: v for k, v in suggested.items() if k in SOURCE_RECONCILE_OVERRIDE_KEYS}
    patch["source_reconcile_enabled"] = True
    patch["source_reconcile_shadow_mode"] = False
    return patch


def build_source_reconcile_rollback_patch() -> dict:
    """Откат: все source_reconcile_* override → None (вернуться к global defaults).

    НЕ очищает speaker_identity_hints и НЕ трогает signal_engine_*.
    """
    return {k: None for k in SOURCE_RECONCILE_OVERRIDE_KEYS}


def _validate_patch_safe(patch: Optional[dict]) -> dict:
    """Прогнать patch через ai_settings.validate_patch. Без raw-дампа в случае ошибки."""
    if patch is None:
        return {"valid": True, "error": None}
    try:
        from ...services.ai_settings import validate_patch
        validate_patch(patch)
        return {"valid": True, "error": None}
    except Exception as e:  # noqa: BLE001 — safe: имя класса, не содержимое patch
        return {"valid": False, "error": type(e).__name__}


def _status_for_verdict(verdict: Optional[str]) -> str:
    return {
        "no_data": "no_data",
        "ready_for_active_source_reconcile_canary": "ready",
        "active_canary_running": "active_running",
    }.get(verdict or "", "not_ready")


def build_full_canary_plan(
    readiness_report: dict,
    *,
    include_shadow_patch: bool = True,
    include_active_patch: bool = True,
    include_rollback_patch: bool = True,
) -> dict:
    """Собрать безопасный operational plan из readiness-отчёта.

    Включает shadow/active/rollback patch (по флагам), их валидацию, safety-чеки и notes.
    Patch'и НЕ применяются — только генерируются для ручного PATCH.
    """
    verdict = readiness_report.get("verdict") if isinstance(readiness_report, dict) else None
    status = _status_for_verdict(verdict)

    shadow = build_shadow_collection_patch() if include_shadow_patch else None
    active = build_active_source_reconcile_patch(readiness_report) if include_active_patch else None
    rollback = build_source_reconcile_rollback_patch() if include_rollback_patch else None
    can_apply_active = active is not None

    patch_validation = {
        "shadow_collection_patch": _validate_patch_safe(shadow),
        "active_source_reconcile_patch": _validate_patch_safe(active),
        "rollback_patch": _validate_patch_safe(rollback),
    }

    recommended_action = {
        "ready": "применить active_source_reconcile_patch на ОДНОЙ канареечной встрече вручную",
        "not_ready": "собрать ещё shadow-данные (shadow_collection_patch) и повторить readiness",
        "no_data": "включить логи/трейс на встречах (shadow_collection_patch) и повторить",
        "active_running": "мониторить actual_attach + unknown_side_event_rate; не расширять",
    }[status]

    all_patches = [p for p in (shadow, active, rollback) if p is not None]
    blob = json.dumps(
        {"shadow": shadow, "active": active, "rollback": rollback}, ensure_ascii=False)
    safety_checks = {
        "does_not_modify_speaker_identity_hints": all(
            not (set(p) & _FORBIDDEN_PATCH_KEYS) for p in all_patches),
        "does_not_enable_signal_engine_active": not any(
            p.get("signal_engine_shadow_mode") is False for p in all_patches),
        "does_not_contain_raw_text": "transcript" not in blob,
        "does_not_contain_raw_source_ids": (
            "audio_source_id" not in blob and "channel_label" not in blob),
        "does_not_contain_raw_speaker_labels": (
            "speaker_label" not in blob and "SM_" not in blob),
    }
    # дополнительный грубый guard по всему сериализованному плану (без печати самих значений)
    plan_blob_clean = not any(tok in blob for tok in _FORBIDDEN_RAW_TOKENS)

    notes = [
        "tool не применяет patch автоматически — применять вручную через PATCH ai-settings",
        "active patch включать только на ОДНОЙ встрече; глобальный rollout не трогаем",
        "rollback обнуляет только source_reconcile_*; speaker_identity_hints и signal_engine_* не очищаются",
        "source/channel/track = зона записи, не сторона; сторона только через speaker_identity_hints",
    ]
    if not plan_blob_clean:
        notes.append("WARN: plan содержит подозрительные подстроки — проверить источник readiness_report")

    return {
        "status": status,
        "recommended_action": recommended_action,
        "can_apply_active_patch": can_apply_active,
        "endpoint_template": ENDPOINT_TEMPLATE,
        "shadow_collection_patch": shadow,
        "active_source_reconcile_patch": active,
        "rollback_patch": rollback,
        "patch_validation": patch_validation,
        "safety_checks": safety_checks,
        "notes": notes,
    }


# --------------------------------------------------------------------------- CLI

def _readiness_from_log(path: str, *, meeting_id=None, session_id=None, check_id=None):
    """(report, None) при успехе; (None, exit_code) при ошибке чтения файла."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {path}", file=sys.stderr)
        return None, 2
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return None, 2
    ev = extract_all_canary_trace_events_from_lines(lines)
    report = analyze_canary_readiness_from_events(
        source_reconcile_events=ev["source_reconcile"], signal_engine_events=ev["signal_engine"],
        meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    return report, None


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="python -m app.core.context.canary_operations",
        description="Canary operations: безопасный plan + PATCH JSON (apply вручную).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="readiness + full canary plan по логу")
    p_plan.add_argument("logfile")
    p_plan.add_argument("--meeting-id", default=None)
    p_plan.add_argument("--session-id", default=None)
    p_plan.add_argument("--check-id", default=None)

    p_active = sub.add_parser("emit-active", help="только active patch (exit 4, если не ready)")
    p_active.add_argument("logfile")
    p_active.add_argument("--meeting-id", default=None)
    p_active.add_argument("--session-id", default=None)
    p_active.add_argument("--check-id", default=None)

    sub.add_parser("emit-rollback", help="rollback patch (лог не нужен)")
    p_shadow = sub.add_parser("emit-shadow", help="shadow collection patch (лог не нужен)")
    p_shadow.add_argument("--trace-sample-rate", type=float, default=None)

    p_mon = sub.add_parser("monitor", help="мониторинг active canary (делегирует active_canary_monitor)")
    p_mon.add_argument("logfile")
    p_mon.add_argument("--meeting-id", default=None)
    p_mon.add_argument("--session-id", default=None)
    p_mon.add_argument("--check-id", default=None)
    p_mon.add_argument("--require-single-meeting", action="store_true")
    p_mon.add_argument("--emit-rollback-if-needed", action="store_true")

    p_pcs = sub.add_parser("monitor-per-channel-stt",
                           help="мониторинг per-channel STT canary (делегирует per_channel_stt_canary_monitor, Этап 19)")
    p_pcs.add_argument("logfile")
    p_pcs.add_argument("--meeting-id", default=None)
    p_pcs.add_argument("--session-id", default=None)
    p_pcs.add_argument("--check-id", default=None)
    p_pcs.add_argument("--require-single-meeting", action="store_true")
    p_pcs.add_argument("--emit-rollback-if-needed", action="store_true")

    p_fr = sub.add_parser("field-report",
                          help="единый field canary report (делегирует field_canary_report, Этап 20)")
    p_fr.add_argument("logfile")
    p_fr.add_argument("--meeting-id", default=None)
    p_fr.add_argument("--session-id", default=None)
    p_fr.add_argument("--check-id", default=None)
    p_fr.add_argument("--provider-cost-per-minute", type=float, default=None)
    p_fr.add_argument("--output", default=None)
    p_fr.add_argument("--emit-next-patch", action="store_true")
    p_fr.add_argument("--require-single-meeting", action="store_true")

    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3

    if ns.command == "emit-rollback":
        _emit({"rollback_patch": build_source_reconcile_rollback_patch(),
               "endpoint_template": ENDPOINT_TEMPLATE})
        return 0

    if ns.command == "emit-shadow":
        _emit({"shadow_collection_patch": build_shadow_collection_patch(
            trace_sample_rate=ns.trace_sample_rate), "endpoint_template": ENDPOINT_TEMPLATE})
        return 0

    if ns.command == "monitor":
        from .active_canary_monitor import run_monitor_cli
        return run_monitor_cli(
            logfile=ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id,
            check_id=ns.check_id, require_single_meeting=ns.require_single_meeting,
            emit_rollback_if_needed=ns.emit_rollback_if_needed)

    if ns.command == "monitor-per-channel-stt":
        from .per_channel_stt_canary_monitor import run_monitor_cli as run_pcs_monitor_cli
        return run_pcs_monitor_cli(
            logfile=ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id,
            check_id=ns.check_id, require_single_meeting=ns.require_single_meeting,
            emit_rollback_if_needed=ns.emit_rollback_if_needed)

    if ns.command == "field-report":
        from .field_canary_report import run_field_report_cli
        return run_field_report_cli(
            logfile=ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id,
            check_id=ns.check_id, cost=ns.provider_cost_per_minute, output=ns.output,
            emit_next_patch=ns.emit_next_patch, require_single_meeting=ns.require_single_meeting)

    if ns.command == "plan":
        report, err = _readiness_from_log(
            ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id, check_id=ns.check_id)
        if err is not None:
            return err
        plan = build_full_canary_plan(report)
        plan["readiness_verdict"] = report.get("verdict")
        plan["trace_scope"] = report.get("trace_scope")
        plan["trace_filters"] = report.get("trace_filters")
        plan["warnings"] = report.get("warnings", [])
        _emit(plan)
        return 0

    if ns.command == "emit-active":
        report, err = _readiness_from_log(
            ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id, check_id=ns.check_id)
        if err is not None:
            return err
        active = build_active_source_reconcile_patch(report)
        if active is None:
            _emit({"error": "not_ready", "verdict": report.get("verdict"),
                   "reason": "readiness != ready_for_active_source_reconcile_canary",
                   "blocking_issues": report.get("blocking_issues", [])})
            return 4
        _emit({"active_source_reconcile_patch": active,
               "patch_validation": _validate_patch_safe(active),
               "endpoint_template": ENDPOINT_TEMPLATE})
        return 0

    return 3


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
