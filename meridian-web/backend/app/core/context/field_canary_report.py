"""Unified field canary report (Этап 20).

По одному meeting_id собирает единый безопасный отчёт о готовности к реальной canary-встрече:
audio/multichannel, per-channel STT provider health/cost/budget, candidate emission readiness,
source reconciliation readiness, speaker hint coverage, Signal Engine health, рекомендация + safe
PATCH-кандидаты. Без БД/LLM/network. Tool ничего не применяет.

Вывод — только агрегаты/категории/флаги. Никакого raw audio/text/source ids/channel labels/speaker
labels/segment ids/candidate ids/device ids/API keys. channel_{index} — техническая зона записи, не сторона.
"""

import argparse
import json
import sys
from typing import Any, Optional

from .active_canary_monitor import analyze_active_canary_run
from .canary_operations import (
    build_active_source_reconcile_patch,
    build_source_reconcile_rollback_patch,
)
from .canary_readiness_analysis import analyze_canary_readiness
from .per_channel_stt_canary_monitor import (
    _pcs_latest,
    analyze_per_channel_stt_canary_run,
    load_per_channel_stt_monitor_events_from_lines,
)
from .per_channel_stt_canary_operations import (
    build_per_channel_stt_emit_candidates_patch,
    build_per_channel_stt_rollback_patch,
    build_per_channel_stt_shadow_patch,
)
from .signal_trace_analysis import analyze_signal_traces
from .source_reconcile_trace_analysis import analyze_source_reconcile_traces

ENDPOINT_TEMPLATE = "/api/meetings/{meeting_id}/ai-settings"


def load_field_canary_events_from_lines(
    lines, *, meeting_id: Any = None, session_id: Any = None, check_id: Optional[str] = None,
) -> dict:
    """Извлечь+отфильтровать три потока trace (делегирует в per-channel monitor loader)."""
    return load_per_channel_stt_monitor_events_from_lines(
        lines, meeting_id=meeting_id, session_id=session_id, check_id=check_id)


def _rate(num, den):
    return round(num / den, 4) if den else 0.0


def analyze_field_canary_report(
    *,
    per_channel_stt_events: list[dict],
    source_reconcile_events: list[dict],
    signal_engine_events: list[dict],
    provider_cost_per_minute: Optional[float] = None,
) -> dict:
    """Единый field-отчёт. Только безопасные агрегаты + safe PATCH-кандидаты."""
    pcs_report = analyze_per_channel_stt_canary_run(
        per_channel_stt_events=per_channel_stt_events, source_reconcile_events=source_reconcile_events,
        signal_engine_events=signal_engine_events)
    active_report = analyze_active_canary_run(
        source_reconcile_events=source_reconcile_events, signal_engine_events=signal_engine_events)
    readiness = analyze_canary_readiness(
        source_reconcile_events=source_reconcile_events, signal_engine_events=signal_engine_events)
    se_an = analyze_signal_traces(signal_engine_events)
    sr_an = analyze_source_reconcile_traces(source_reconcile_events)

    pcs_total = len(per_channel_stt_events)
    sr_total = sr_an["total"]
    se_total = se_an["total"]
    total_events = pcs_total + sr_total + se_total

    L = _pcs_latest(per_channel_stt_events)
    pcs_block_src = pcs_report["per_channel_stt"]
    provider = L.get("provider")
    detected_provider = provider if (provider and provider != "noop") else None

    # --- audio ---
    mc = se_an.get("audio_multichannel", {})
    cap = se_an.get("audio_capture", {})
    mc_p50 = mc.get("max_channels_seen_p50")
    audio = {
        "multichannel_seen": bool(mc_p50 is not None and mc_p50 >= 2)
        or bool(L.get("max_channels_seen", 0) and L.get("max_channels_seen", 0) >= 2),
        "max_channels_seen_p50": mc_p50,
        "v2_parse_errors": int(mc.get("parse_error_count_p50") or 0),
        "v2_sequence_gaps": int(mc.get("sequence_gap_count_p50") or 0),
        "capture_routes": cap.get("by_route", {}),
        "capture_pipelines": cap.get("by_pipeline", {}),
    }

    # --- per_channel_stt ---
    per_channel_block = {
        "total": pcs_total,
        "provider": provider,
        "enabled": bool(L.get("enabled", False)),
        "shadow_mode": L.get("shadow_mode"),
        "transcribe_success_count": pcs_block_src["transcribe_success_count"],
        "candidate_shadow_suppressed_count": pcs_block_src["candidate_shadow_suppressed_count"],
        "candidate_emit_count": pcs_block_src["candidate_emit_count"],
        "adapter_unavailable_count": pcs_block_src["adapter_unavailable_count"],
        "api_key_missing_count": pcs_block_src["api_key_missing_count"],
        "timeout_count": pcs_block_src["timeout_count"],
        "provider_error_count": pcs_block_src["provider_error_count"],
        "budget_exhausted_count": pcs_block_src["budget_exhausted_count"],
        "cache_hit_rate": pcs_block_src["cache_hit_rate"],
        "average_dominance_p50": pcs_block_src["average_dominance_p50"],
        "average_transcribe_latency_p95_ms": pcs_block_src["average_transcribe_latency_p95_ms"],
    }
    candidate_emit = per_channel_block["candidate_emit_count"]
    transcribe_success = per_channel_block["transcribe_success_count"]
    shadow_suppressed = per_channel_block["candidate_shadow_suppressed_count"]

    # --- source_reconciliation ---
    by_match = sr_an.get("by_match_reason", {})
    source_block = {
        "total": sr_total,
        "would_attach_rate": sr_an.get("would_attach_rate"),
        "actual_attach_rate": sr_an.get("actual_attach_rate"),
        "by_match_reason": by_match,
        "score_p50": (sr_an.get("score") or {}).get("p50"),
        "low_overlap_rate": _rate(by_match.get("low_overlap", 0), sr_total),
        "low_text_similarity_rate": _rate(by_match.get("low_text_similarity", 0), sr_total),
        "ambiguous_rate": _rate(by_match.get("ambiguous", 0), sr_total),
    }
    sr_would = source_block["would_attach_rate"]
    sr_actual = source_block["actual_attach_rate"]

    # --- speaker_context ---
    sc = se_an.get("speaker_context", {}) if isinstance(se_an.get("speaker_context"), dict) else {}
    speaker_block = {
        "unknown_side_event_rate": sc.get("unknown_side_event_rate"),
        "hint_source_event_rate": sc.get("hint_source_event_rate"),
        "audio_linked_event_rate": sc.get("audio_linked_event_rate"),
        "avg_speaker_confidence_p50": sc.get("avg_speaker_confidence_p50"),
    }
    unk = speaker_block["unknown_side_event_rate"]
    hint = speaker_block["hint_source_event_rate"]

    # --- signal_engine ---
    by_err = se_an.get("by_error_kind", {})
    signal_block = {
        "total": se_total,
        "would_prompt_rate": se_an.get("would_prompt_rate"),
        "actual_prompt_rate": se_an.get("actual_prompt_rate"),
        "timeout_exception_rate": (_rate(by_err.get("timeout", 0) + by_err.get("exception", 0), se_total)
                                   if se_total else None),
        "latency_p95_ms": (se_an.get("latency_ms") or {}).get("p95"),
    }

    # --- cost_usage ---
    calls_used = L.get("provider_calls_used")
    audio_seconds = L.get("provider_audio_seconds_used")
    audio_minutes = round(audio_seconds / 60.0, 4) if isinstance(audio_seconds, (int, float)) else None
    estimated_cost = (round(audio_minutes * float(provider_cost_per_minute), 4)
                      if (audio_minutes is not None and provider_cost_per_minute is not None) else None)
    cost_usage = {
        "provider_call_count": int(calls_used) if isinstance(calls_used, (int, float)) else None,
        "provider_audio_seconds": float(audio_seconds) if isinstance(audio_seconds, (int, float)) else None,
        "provider_audio_minutes": audio_minutes,
        "estimated_cost": estimated_cost,
        "cost_per_minute_used": provider_cost_per_minute,
        "cache_hit_rate": per_channel_block["cache_hit_rate"],
        "budget_exhausted_count": per_channel_block["budget_exhausted_count"],
    }

    # --- patches ---
    patches = {
        "per_channel_shadow_patch": build_per_channel_stt_shadow_patch(
            provider=detected_provider or "noop"),
        "per_channel_emit_candidates_patch": build_per_channel_stt_emit_candidates_patch(pcs_report),
        "per_channel_rollback_patch": build_per_channel_stt_rollback_patch(),
        "source_reconcile_active_patch": build_active_source_reconcile_patch(readiness),
        "source_reconcile_rollback_patch": build_source_reconcile_rollback_patch(),
    }

    # --- статус ---
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    needs_hints = ((candidate_emit > 0 or sr_total > 0)
                   and unk is not None and unk > 0.5 and hint is not None and hint < 0.2)

    if total_events == 0:
        status = "no_data"
        primary = "enable_multichannel_shadow"
        blockers.append("нет trace events (PER_CHANNEL_STT/SOURCE_RECONCILE/SIGNAL_ENGINE)")
    elif pcs_report["rollback_recommended"]:
        status = "rollback_recommended"
        primary = "rollback_per_channel_stt"
        blockers.extend(pcs_report.get("blocking_issues", []))
    elif active_report["rollback_recommended"]:
        status = "rollback_recommended"
        primary = "rollback_source_reconcile"
        blockers.extend(active_report.get("blocking_issues", []))
    elif sr_actual is not None and sr_actual > 0:
        if needs_hints:
            status = "needs_hints"
            primary = "add_speaker_identity_hints"
        elif active_report["status"] == "healthy":
            status = "healthy"
            primary = "continue_canary"
        else:
            status = "active_source_reconcile_running"
            primary = "continue_canary"
        warnings.extend(active_report.get("warnings", []))
    elif candidate_emit > 0 and sr_would is not None and sr_would > 0:
        if needs_hints:
            status = "needs_hints"
            primary = "add_speaker_identity_hints"
        elif readiness.get("verdict") == "ready_for_active_source_reconcile_canary":
            status = "source_reconcile_ready"
            primary = "enable_source_reconcile_active_canary"
        else:
            status = "source_reconcile_ready"
            primary = "continue_canary"
            blockers.extend(readiness.get("blocking_issues", []))
    elif candidate_emit > 0:
        status = "not_ready"
        primary = "check_timestamps"
        warnings.append("candidates эмитятся, но source_reconcile не матчит — проверить timestamps/text similarity")
    elif needs_hints:
        status = "needs_hints"
        primary = "add_speaker_identity_hints"
    elif pcs_report["status"] == "ready_for_candidate_emit":
        status = "candidate_emit_ready"
        primary = "emit_per_channel_candidates"
    elif pcs_report["status"] == "provider_unavailable":
        status = "not_ready"
        primary = "configure_provider"
        blockers.extend(pcs_report.get("blocking_issues", []))
    elif pcs_total == 0 or not audio["multichannel_seen"]:
        status = "not_ready"
        primary = "enable_multichannel_shadow"
        notes.append("нет per-channel событий или multichannel < 2 каналов")
    elif transcribe_success > 0 and shadow_suppressed > 0:
        status = "per_channel_shadow_ready"
        primary = "emit_per_channel_candidates"
    elif total_events < 5:
        status = "collecting"
        primary = "collect_more_data"
    else:
        status = "not_ready"
        primary = "collect_more_data"

    # доп. warnings/notes
    if source_block["low_overlap_rate"] > 0.25:
        warnings.append("low_overlap высок — проверить timestamp-шкалы каналов")
    if source_block["low_text_similarity_rate"] > 0.25:
        warnings.append("low_text_similarity высок — проверить расхождение transcripts")
    if needs_hints:
        notes.append("links/candidates есть, но unknown side высок и hint coverage низкий — добавить "
                     "speaker_identity_hints (значения задаёт оператор, не tool)")

    # --- safety_checks ---
    data_blob = json.dumps({
        "audio": audio, "per_channel_stt": per_channel_block, "source_reconciliation": source_block,
        "speaker_context": speaker_block, "signal_engine": signal_block, "cost_usage": cost_usage,
        "patches": patches, "blocking_issues": blockers, "warnings": warnings, "notes": notes,
        "status": status, "primary_recommendation": primary,
    }, ensure_ascii=False)
    all_patches = [p for p in patches.values() if isinstance(p, dict)]
    safety_checks = {
        "single_meeting_scope_recommended": True,
        "does_not_contain_raw_text": "transcript" not in data_blob,
        # raw audio в коде живёт как pcm16_mono bytes; имя config-ключа max_wav_bytes — не утечка
        "does_not_contain_raw_audio": "pcm16_mono" not in data_blob and "RIFF" not in data_blob,
        "does_not_contain_raw_source_ids": (
            "audio_source_id" not in data_blob and "channel_label" not in data_blob),
        "does_not_contain_raw_speaker_labels": "speaker_label" not in data_blob and "SM_" not in data_blob,
        "does_not_contain_segment_ids": "segment_id" not in data_blob and "candidate_id" not in data_blob,
        "does_not_contain_api_keys": (
            "xi-api-key" not in data_blob and "Authorization" not in data_blob
            and "Bearer " not in data_blob and "sk_live" not in data_blob),
        "patches_do_not_enable_signal_engine_active": not any(
            p.get("signal_engine_shadow_mode") is False for p in all_patches),
        "patches_do_not_modify_speaker_identity_hints": all(
            "speaker_identity_hints" not in p for p in all_patches),
    }

    return {
        "status": status,
        "primary_recommendation": primary,
        "blocking_issues": blockers,
        "warnings": warnings,
        "notes": notes,
        "audio": audio,
        "per_channel_stt": per_channel_block,
        "source_reconciliation": source_block,
        "speaker_context": speaker_block,
        "signal_engine": signal_block,
        "cost_usage": cost_usage,
        "patches": patches,
        "safety_checks": safety_checks,
    }


# --------------------------------------------------------------------------- next patch

def _next_patch(report: dict) -> Optional[dict]:
    """Рекомендованный следующий patch по status (или None)."""
    p = report.get("patches", {})
    status = report.get("status")
    if status == "rollback_recommended":
        if report.get("primary_recommendation") == "rollback_source_reconcile":
            return {"name": "source_reconcile_rollback_patch", "patch": p.get("source_reconcile_rollback_patch")}
        return {"name": "per_channel_rollback_patch", "patch": p.get("per_channel_rollback_patch")}
    if status in ("candidate_emit_ready", "per_channel_shadow_ready") and p.get("per_channel_emit_candidates_patch"):
        return {"name": "per_channel_emit_candidates_patch", "patch": p["per_channel_emit_candidates_patch"]}
    if status == "source_reconcile_ready" and p.get("source_reconcile_active_patch"):
        return {"name": "source_reconcile_active_patch", "patch": p["source_reconcile_active_patch"]}
    return None


# --------------------------------------------------------------------------- CLI

def _build_report_from_log(path, *, meeting_id=None, session_id=None, check_id=None, cost=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {path}", file=sys.stderr)
        return None, 2
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return None, 2
    loaded = load_field_canary_events_from_lines(
        lines, meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    report = analyze_field_canary_report(
        per_channel_stt_events=loaded["per_channel_stt"],
        source_reconcile_events=loaded["source_reconcile"],
        signal_engine_events=loaded["signal_engine"],
        provider_cost_per_minute=cost)
    report["trace_scope"] = loaded["trace_scope"]
    report["trace_filters"] = loaded["trace_filters"]
    if loaded["trace_scope"].get("has_mixed_meetings"):
        report.setdefault("warnings", []).append(
            "лог содержит несколько meeting_id — отчёт лучше считать по одной встрече (--meeting-id)")
    return report, None


def run_field_report_cli(*, logfile, meeting_id=None, session_id=None, check_id=None, cost=None,
                         output=None, emit_next_patch=False, require_single_meeting=False) -> int:
    report, err = _build_report_from_log(
        logfile, meeting_id=meeting_id, session_id=session_id, check_id=check_id, cost=cost)
    if err is not None:
        return err

    if require_single_meeting and report["trace_scope"].get("has_mixed_meetings"):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 4

    if emit_next_patch:
        nxt = _next_patch(report)
        if nxt is None or nxt.get("patch") is None:
            print(json.dumps({"error": "no_safe_next_patch", "status": report.get("status"),
                              "primary_recommendation": report.get("primary_recommendation")},
                             ensure_ascii=False, indent=2))
            return 4
        print(json.dumps({"next_patch_name": nxt["name"], "patch": nxt["patch"],
                          "endpoint_template": ENDPOINT_TEMPLATE}, ensure_ascii=False, indent=2))
        return 0

    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            print(f"Ошибка записи: {e}", file=sys.stderr)
            return 2
        print(json.dumps({"written": output, "status": report.get("status")}, ensure_ascii=False))
    else:
        print(blob)
    return 0


def _main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        prog="python -m app.core.context.field_canary_report",
        description="Единый field canary report по одной встрече (--meeting-id).")
    parser.add_argument("logfile")
    parser.add_argument("--meeting-id", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--check-id", default=None)
    parser.add_argument("--provider-cost-per-minute", type=float, default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--emit-next-patch", action="store_true")
    parser.add_argument("--require-single-meeting", action="store_true")
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3
    return run_field_report_cli(
        logfile=ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id, check_id=ns.check_id,
        cost=ns.provider_cost_per_minute, output=ns.output, emit_next_patch=ns.emit_next_patch,
        require_single_meeting=ns.require_single_meeting)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
