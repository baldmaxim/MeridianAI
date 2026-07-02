"""Per-channel STT canary operations toolkit (Этап 19).

Backend-only генератор безопасных operational plan и PATCH JSON для запуска Stage 18 per-channel STT
canary на ОДНОЙ встрече: shadow → candidate-emission → rollback. Tool НЕ применяет patch, НЕ ходит в
сеть, НЕ читает БД, НЕ включает source_reconcile active и НЕ включает Signal Engine active.

Вывод — только агрегаты/флаги. Никакого raw audio/text/source ids/labels/API keys.
"""

import argparse
import json
import sys
from typing import Optional

from .per_channel_stt_canary_monitor import (
    analyze_per_channel_stt_canary_run,
    load_per_channel_stt_monitor_events_from_lines,
)

# Все скрытые per-meeting override-ключи per-channel STT (Этап 17 + 18).
PER_CHANNEL_STT_OVERRIDE_KEYS = [
    "audio_per_channel_stt_enabled",
    "audio_per_channel_stt_shadow_mode",
    "audio_per_channel_stt_trace_enabled",
    "audio_per_channel_stt_trace_sample_rate",
    "audio_per_channel_stt_max_channels",
    "audio_per_channel_stt_min_rms",
    "audio_per_channel_stt_min_dominance",
    "audio_per_channel_stt_min_segment_ms",
    "audio_per_channel_stt_end_silence_ms",
    "audio_per_channel_stt_max_segment_ms",
    "audio_per_channel_stt_min_text_chars",
    "audio_per_channel_stt_max_segments_per_minute",
    "audio_per_channel_stt_max_concurrent_transcribes",
    "audio_per_channel_stt_provider",
    "audio_per_channel_stt_timeout_seconds",
    "audio_per_channel_stt_language_code",
    "audio_per_channel_stt_model_id",
    "audio_per_channel_stt_cache_enabled",
    "audio_per_channel_stt_cache_max_entries",
    "audio_per_channel_stt_max_audio_seconds",
    "audio_per_channel_stt_max_wav_bytes",
    "audio_per_channel_stt_max_provider_calls_per_meeting",
    "audio_per_channel_stt_max_provider_audio_seconds_per_meeting",
]

# Разрешённые source_reconcile-ключи в emit-candidates (только shadow-safe).
_SR_SHADOW_KEYS = {"source_reconcile_enabled", "source_reconcile_shadow_mode", "source_reconcile_trace_enabled"}
_FORBIDDEN_PATCH_KEYS = {"speaker_identity_hints"}
ENDPOINT_TEMPLATE = "/api/meetings/{meeting_id}/ai-settings"
_FORBIDDEN_RAW_TOKENS = (
    "transcript", "speaker_label", "audio_source_id", "channel_label", "segment_id",
    "candidate_id", "SM_", "Speaker ", "xi-api-key", "Authorization", "Bearer ", "sk_live",
)


def build_per_channel_stt_shadow_patch(
    *,
    provider: str = "noop",
    trace_sample_rate: Optional[float] = None,
    max_provider_calls_per_meeting: Optional[int] = None,
    max_provider_audio_seconds_per_meeting: Optional[float] = None,
    min_dominance: Optional[float] = None,
    max_channels: Optional[int] = None,
) -> dict:
    """Patch для shadow-сбора per-channel STT. provider='noop' безопасен; для реального canary —
    'elevenlabs_batch'. НЕ трогает source_reconcile/signal_engine/speaker_identity_hints."""
    patch: dict = {
        "audio_per_channel_stt_enabled": True,
        "audio_per_channel_stt_shadow_mode": True,
        "audio_per_channel_stt_trace_enabled": True,
        "audio_per_channel_stt_provider": str(provider or "noop").strip().lower()[:40],
    }
    if trace_sample_rate is not None:
        patch["audio_per_channel_stt_trace_sample_rate"] = max(0.0, min(1.0, float(trace_sample_rate)))
    if max_provider_calls_per_meeting is not None:
        patch["audio_per_channel_stt_max_provider_calls_per_meeting"] = max(0, min(1000, int(max_provider_calls_per_meeting)))
    if max_provider_audio_seconds_per_meeting is not None:
        patch["audio_per_channel_stt_max_provider_audio_seconds_per_meeting"] = max(
            0.0, min(7200.0, float(max_provider_audio_seconds_per_meeting)))
    if min_dominance is not None:
        patch["audio_per_channel_stt_min_dominance"] = max(0.0, min(1.0, float(min_dominance)))
    if max_channels is not None:
        patch["audio_per_channel_stt_max_channels"] = max(1, min(8, int(max_channels)))
    return patch


def build_per_channel_stt_emit_candidates_patch(readiness_report: dict) -> Optional[dict]:
    """Patch: per-channel STT из shadow → candidate-emission. None, если не ready.

    Ставит audio_per_channel_stt_shadow_mode=false + держит source_reconcile shadow-safe
    (shadow_mode=true). НЕ включает source_reconcile active, НЕ трогает signal_engine/hints.
    """
    if not isinstance(readiness_report, dict):
        return None
    if readiness_report.get("status") != "ready_for_candidate_emit":
        return None
    suggested = readiness_report.get("suggested_patch") or {}
    allowed = set(PER_CHANNEL_STT_OVERRIDE_KEYS) | _SR_SHADOW_KEYS
    patch = {k: v for k, v in suggested.items() if k in allowed}
    patch["audio_per_channel_stt_enabled"] = True
    patch["audio_per_channel_stt_shadow_mode"] = False
    # source_reconcile остаётся shadow-safe (НИКОГДА не false здесь)
    patch["source_reconcile_enabled"] = True
    patch["source_reconcile_shadow_mode"] = True
    patch["source_reconcile_trace_enabled"] = True
    return patch


def build_per_channel_stt_rollback_patch() -> dict:
    """Откат: все audio_per_channel_stt_* → None. НЕ очищает source_reconcile_*/signal_engine_*/hints."""
    return {k: None for k in PER_CHANNEL_STT_OVERRIDE_KEYS}


def _validate_patch_safe(patch: Optional[dict]) -> dict:
    if patch is None:
        return {"valid": True, "error": None}
    try:
        from ...services.ai_settings import validate_patch
        validate_patch(patch)
        return {"valid": True, "error": None}
    except Exception as e:  # noqa: BLE001 — имя класса, не содержимое patch
        return {"valid": False, "error": type(e).__name__}


def _status_for(readiness_status: Optional[str]) -> str:
    return {
        "no_data": "no_data",
        "ready_for_candidate_emit": "ready",
        "candidate_emit_running": "candidate_emit_running",
        "rollback_recommended": "rollback_recommended",
    }.get(readiness_status or "", "not_ready")


def build_per_channel_stt_canary_plan(
    readiness_report: dict,
    *,
    include_shadow_patch: bool = True,
    include_emit_candidates_patch: bool = True,
    include_rollback_patch: bool = True,
) -> dict:
    """Собрать безопасный operational plan из readiness-отчёта монитора."""
    r_status = readiness_report.get("status") if isinstance(readiness_report, dict) else None
    status = _status_for(r_status)

    shadow = build_per_channel_stt_shadow_patch() if include_shadow_patch else None
    emit = build_per_channel_stt_emit_candidates_patch(readiness_report) if include_emit_candidates_patch else None
    rollback = build_per_channel_stt_rollback_patch() if include_rollback_patch else None
    can_emit = emit is not None

    patch_validation = {
        "shadow_patch": _validate_patch_safe(shadow),
        "emit_candidates_patch": _validate_patch_safe(emit),
        "rollback_patch": _validate_patch_safe(rollback),
    }
    recommended_action = {
        "ready": "применить emit_candidates_patch на ОДНОЙ встрече (per-channel shadow→emit; source_reconcile остаётся shadow)",
        "not_ready": "собрать ещё shadow-данные (shadow_patch с provider) и повторить мониторинг",
        "no_data": "включить multichannel shadow (Stage 16) + per-channel STT shadow, собрать trace",
        "candidate_emit_running": "мониторить source_reconcile would_attach; source_reconcile active — отдельно (Stage 13/14)",
        "rollback_recommended": "применить rollback_patch (provider errors/latency)",
    }[status]

    all_patches = [p for p in (shadow, emit, rollback) if p is not None]
    blob = json.dumps({"shadow": shadow, "emit": emit, "rollback": rollback}, ensure_ascii=False)
    safety_checks = {
        "does_not_modify_speaker_identity_hints": all(
            not (set(p) & _FORBIDDEN_PATCH_KEYS) for p in all_patches),
        "does_not_enable_source_reconcile_active": not any(
            p.get("source_reconcile_shadow_mode") is False for p in all_patches),
        "does_not_enable_signal_engine_active": not any(
            p.get("signal_engine_shadow_mode") is False for p in all_patches),
        "does_not_contain_raw_text": "transcript" not in blob,
        "does_not_contain_raw_source_ids": "audio_source_id" not in blob and "channel_label" not in blob,
        "does_not_contain_raw_speaker_labels": "speaker_label" not in blob and "SM_" not in blob,
        "does_not_contain_segment_ids": "segment_id" not in blob and "candidate_id" not in blob,
        # реальные индикаторы ключа/заголовка, НЕ слово "api_key" (легитимно в патч-ключах нет, но guard)
        "does_not_contain_api_key": (
            "xi-api-key" not in blob and "Authorization" not in blob
            and "Bearer " not in blob and "sk_live" not in blob),
    }
    notes = [
        "tool не применяет patch — применять вручную через PATCH ai-settings",
        "emit_candidates держит source_reconcile shadow=true; source_reconcile active — отдельно (Stage 13/14)",
        "rollback обнуляет только audio_per_channel_stt_*; source_reconcile/signal_engine/hints не трогаются",
        "channel_{index} = техническая зона записи, не сторона; сторона только через speaker_identity_hints",
    ]

    return {
        "status": status,
        "recommended_action": recommended_action,
        "can_emit_candidates": can_emit,
        "endpoint_template": ENDPOINT_TEMPLATE,
        "shadow_patch": shadow,
        "emit_candidates_patch": emit,
        "rollback_patch": rollback,
        "patch_validation": patch_validation,
        "safety_checks": safety_checks,
        "notes": notes,
        "readiness_status": r_status,
    }


# --------------------------------------------------------------------------- CLI

def _readiness_from_log(path, *, meeting_id=None, session_id=None, check_id=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {path}", file=sys.stderr)
        return None, 2
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return None, 2
    loaded = load_per_channel_stt_monitor_events_from_lines(
        lines, meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    report = analyze_per_channel_stt_canary_run(
        per_channel_stt_events=loaded["per_channel_stt"],
        source_reconcile_events=loaded["source_reconcile"],
        signal_engine_events=loaded["signal_engine"])
    report["trace_scope"] = loaded["trace_scope"]
    report["trace_filters"] = loaded["trace_filters"]
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
        prog="python -m app.core.context.per_channel_stt_canary_operations",
        description="Per-channel STT canary operations: safe plan + PATCH JSON (apply вручную).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sh = sub.add_parser("emit-shadow", help="shadow patch (лог не нужен)")
    p_sh.add_argument("--provider", default="noop")
    p_sh.add_argument("--trace-sample-rate", type=float, default=None)
    p_sh.add_argument("--max-provider-calls", type=int, default=None)
    p_sh.add_argument("--max-provider-audio-seconds", type=float, default=None)
    p_sh.add_argument("--min-dominance", type=float, default=None)
    p_sh.add_argument("--max-channels", type=int, default=None)

    sub.add_parser("emit-rollback", help="rollback patch (лог не нужен)")

    for name in ("plan", "emit-candidates"):
        pp = sub.add_parser(name)
        pp.add_argument("logfile")
        pp.add_argument("--meeting-id", default=None)
        pp.add_argument("--session-id", default=None)
        pp.add_argument("--check-id", default=None)

    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3

    if ns.command == "emit-shadow":
        _emit({"shadow_patch": build_per_channel_stt_shadow_patch(
            provider=ns.provider, trace_sample_rate=ns.trace_sample_rate,
            max_provider_calls_per_meeting=ns.max_provider_calls,
            max_provider_audio_seconds_per_meeting=ns.max_provider_audio_seconds,
            min_dominance=ns.min_dominance, max_channels=ns.max_channels),
            "endpoint_template": ENDPOINT_TEMPLATE})
        return 0

    if ns.command == "emit-rollback":
        _emit({"rollback_patch": build_per_channel_stt_rollback_patch(),
               "endpoint_template": ENDPOINT_TEMPLATE})
        return 0

    if ns.command == "plan":
        report, err = _readiness_from_log(
            ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id, check_id=ns.check_id)
        if err is not None:
            return err
        plan = build_per_channel_stt_canary_plan(report)
        plan["trace_scope"] = report.get("trace_scope")
        plan["trace_filters"] = report.get("trace_filters")
        _emit(plan)
        return 0

    if ns.command == "emit-candidates":
        report, err = _readiness_from_log(
            ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id, check_id=ns.check_id)
        if err is not None:
            return err
        emit = build_per_channel_stt_emit_candidates_patch(report)
        if emit is None:
            _emit({"error": "not_ready", "status": report.get("status"),
                   "reason": "readiness != ready_for_candidate_emit",
                   "blocking_issues": report.get("blocking_issues", [])})
            return 4
        _emit({"emit_candidates_patch": emit, "patch_validation": _validate_patch_safe(emit),
               "endpoint_template": ENDPOINT_TEMPLATE})
        return 0

    return 3


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
