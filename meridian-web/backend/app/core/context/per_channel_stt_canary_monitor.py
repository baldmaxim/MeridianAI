"""Per-channel STT canary monitor (Этап 19).

Читает PER_CHANNEL_STT_TRACE + SOURCE_RECONCILE_TRACE + SIGNAL_ENGINE_TRACE, фильтрует по
meeting_id/session_id/check_id, определяет готовность per-channel STT к переходу shadow_mode=false и
выдаёт безопасную рекомендацию (+ rollback patch, НЕ применяет). Без БД/LLM/network.

Вывод — только агрегаты/категории/флаги. Никакого raw audio/text/source ids/channel labels/speaker
labels/segment ids/API keys. channel_{index} — техническая зона записи, не сторона.
"""

import argparse
import json
import sys
from typing import Any, Iterable, Optional

from .canary_trace_filter import filter_trace_events
from .per_channel_stt_trace_analysis import extract_per_channel_stt_json_from_line
from .signal_trace_analysis import analyze_signal_traces, extract_trace_json_from_line
from .source_reconcile_trace_analysis import (
    analyze_source_reconcile_traces,
    extract_source_reconcile_json_from_line,
)

_FORBIDDEN_RAW_TOKENS = (
    "transcript", "speaker_label", "audio_source_id", "channel_label", "segment_id",
    "candidate_id", "SM_", "Speaker ", "api_key", "Authorization", "xi-api-key",
)


def _rate(num: float, den: float) -> float:
    return round(num / den, 4) if den else 0.0


def _distinct_scope(*event_lists) -> dict:
    meetings: set = set()
    sessions: set = set()
    counts = [len(lst) for lst in event_lists]
    for lst in event_lists:
        for e in lst:
            if not isinstance(e, dict):
                continue
            mid = e.get("meeting_id")
            if mid is not None and str(mid).strip() not in ("", "None"):
                meetings.add(str(mid))
            sid = e.get("session_id")
            if sid is not None and str(sid).strip() not in ("", "None"):
                sessions.add(str(sid))
    return {
        "per_channel_stt_event_count": counts[0] if len(counts) > 0 else 0,
        "source_reconcile_event_count": counts[1] if len(counts) > 1 else 0,
        "signal_engine_event_count": counts[2] if len(counts) > 2 else 0,
        "distinct_meeting_count": len(meetings) if meetings else None,
        "distinct_session_count": len(sessions) if sessions else None,
        "has_mixed_meetings": len(meetings) > 1,
        "has_mixed_sessions": len(sessions) > 1,
    }


def load_per_channel_stt_monitor_events_from_lines(
    lines: Iterable[str], *, meeting_id: Any = None, session_id: Any = None,
    check_id: Optional[str] = None,
) -> dict:
    """Извлечь и отфильтровать три потока trace + безопасные scope/filters."""
    pcs: list[dict] = []
    sr: list[dict] = []
    se: list[dict] = []
    for line in lines:
        o = extract_per_channel_stt_json_from_line(line)
        if o is not None:
            pcs.append(o)
            continue
        o = extract_source_reconcile_json_from_line(line)
        if o is not None:
            sr.append(o)
            continue
        o = extract_trace_json_from_line(line)
        if o is not None:
            se.append(o)

    pre_scope = _distinct_scope(pcs, sr, se)
    pcs_f, s1 = filter_trace_events(pcs, meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    sr_f, s2 = filter_trace_events(sr, meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    se_f, s3 = filter_trace_events(se, meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    return {
        "per_channel_stt": pcs_f,
        "source_reconcile": sr_f,
        "signal_engine": se_f,
        "trace_scope": _distinct_scope(pcs_f, sr_f, se_f),
        "trace_filters": {
            "filters_applied": s1["filters_applied"],
            "filter_hashes": s1["filter_hashes"],
            "per_channel_stt": {"input_count": s1["input_count"], "output_count": s1["output_count"]},
            "source_reconcile": {"input_count": s2["input_count"], "output_count": s2["output_count"]},
            "signal_engine": {"input_count": s3["input_count"], "output_count": s3["output_count"]},
            "pre_filter_has_mixed_meetings": pre_scope["has_mixed_meetings"],
        },
    }


def _pcs_latest(events: list[dict]) -> dict:
    """Последний (самый полный) cumulative-снимок per-channel STT по frame_count."""
    if not events:
        return {}
    return max(events, key=lambda e: e.get("frame_count", 0) if isinstance(e.get("frame_count"), (int, float)) else 0)


def _counter(events: list[dict], field: str) -> dict:
    out: dict = {}
    for e in events:
        v = e.get(field)
        if v:
            out[str(v)] = out.get(str(v), 0) + 1
    return out


def analyze_per_channel_stt_canary_run(
    *,
    per_channel_stt_events: list[dict],
    source_reconcile_events: list[dict],
    signal_engine_events: list[dict],
    min_events: int = 5,
    min_transcribe_success_count: int = 1,
    min_shadow_suppressed_count: int = 1,
    max_timeout_rate: float = 0.10,
    max_provider_error_rate: float = 0.10,
    max_budget_exhausted_rate: float = 0.10,
    max_adapter_unavailable_rate: float = 0.05,
    max_avg_latency_p95_ms: float = 20000.0,
    min_avg_dominance_p50: float = 0.65,
) -> dict:
    """Безопасный отчёт о per-channel STT canary + рекомендация. Только агрегаты."""
    sr = analyze_source_reconcile_traces(source_reconcile_events)
    se = analyze_signal_traces(signal_engine_events)
    pcs_total = len(per_channel_stt_events)
    sr_total = sr["total"]
    se_total = se["total"]

    L = _pcs_latest(per_channel_stt_events)
    enabled_count = sum(1 for e in per_channel_stt_events if e.get("enabled"))
    seg_finalized = int(L.get("segment_finalized_count", 0) or 0)
    transcribe_success = int(L.get("transcribe_success_count", 0) or 0)
    candidate_emit = int(L.get("candidate_emit_count", 0) or 0)
    shadow_suppressed = int(L.get("candidate_shadow_suppressed_count", 0) or 0)
    adapter_unavailable = int(L.get("adapter_unavailable_count", 0) or 0)
    timeout_count = int(L.get("transcribe_timeout_count", 0) or 0)
    provider_error_count = int(L.get("transcribe_provider_error_count", 0) or 0)
    budget_exhausted_count = int(L.get("transcribe_budget_exhausted_count", 0) or 0)
    low_dominance_drops = int(L.get("segment_dropped_low_dominance_count", 0) or 0)
    cache_hit = int(L.get("transcribe_cache_hit_count", 0) or 0)
    cache_miss = int(L.get("transcribe_cache_miss_count", 0) or 0)
    cache_hit_rate = _rate(cache_hit, cache_hit + cache_miss) if (cache_hit + cache_miss) else None
    max_channels_seen = int(L.get("max_channels_seen", 0) or 0)
    avg_dominance = L.get("average_dominance")
    latency_p95 = L.get("average_transcribe_latency_ms")
    provider = L.get("provider")
    last_error_kind = L.get("last_error_kind")
    by_provider = _counter(per_channel_stt_events, "provider")
    by_last_error_kind = _counter(per_channel_stt_events, "last_error_kind")
    api_key_missing_count = by_last_error_kind.get("api_key_missing", 0)

    # multichannel: из per-channel snapshot или из SIGNAL_ENGINE_TRACE audio_multichannel
    mc_p50 = (se.get("audio_multichannel") or {}).get("max_channels_seen_p50")
    mc = max_channels_seen if max_channels_seen else (mc_p50 if mc_p50 is not None else 0)

    base = max(seg_finalized, 1)
    timeout_rate = _rate(timeout_count, base)
    provider_error_rate = _rate(provider_error_count, base)
    budget_exhausted_rate = _rate(budget_exhausted_count, base)
    adapter_unavailable_rate = _rate(adapter_unavailable, base)

    sr_would_attach_rate = sr.get("would_attach_rate")
    sr_actual_attach_rate = sr.get("actual_attach_rate")

    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    suggested_patch: Optional[dict] = None
    rollback_recommended = False

    # active_state
    if enabled_count == 0 and pcs_total == 0:
        active_state = "disabled"
    elif candidate_emit > 0:
        active_state = "candidate_emitting"
    else:
        active_state = "shadow_only"

    provider_noop_only = bool(by_provider) and set(by_provider) <= {"noop"}
    dominance_ok = avg_dominance is None or avg_dominance >= min_avg_dominance_p50
    severe_provider = (timeout_rate > max_timeout_rate or provider_error_rate > max_provider_error_rate
                       or (latency_p95 is not None and latency_p95 > max_avg_latency_p95_ms))

    # --- основной разбор ---
    if pcs_total == 0 and sr_total == 0 and se_total == 0:
        status = "no_data"
        primary = "enable_multichannel_shadow"
        blockers.append("нет trace events (PER_CHANNEL_STT/SOURCE_RECONCILE/SIGNAL_ENGINE)")
    elif pcs_total == 0 and (mc is None or mc < 2):
        status = "no_multichannel"
        primary = "enable_multichannel_shadow"
        notes.append("нет PER_CHANNEL_STT_TRACE и multichannel < 2 каналов — включить Stage 16 shadow")
    elif pcs_total == 0:
        status = "no_multichannel"
        primary = "collect_more_data"
        notes.append("multichannel есть (2+ канала), но per-channel STT canary не активен — включить")
    elif (api_key_missing_count > 0 or last_error_kind in ("api_key_missing", "unknown_provider")
          or provider_noop_only or (adapter_unavailable > 0 and transcribe_success == 0)):
        status = "provider_unavailable"
        primary = "configure_provider"
        if api_key_missing_count > 0 or last_error_kind == "api_key_missing":
            blockers.append("api_key_missing — задать ключ провайдера (server-side)")
        elif last_error_kind == "unknown_provider":
            blockers.append("unknown_provider — задать корректный provider")
        elif provider_noop_only:
            notes.append("provider=noop — задать реальный provider (elevenlabs_batch)")
        else:
            notes.append("adapter unavailable — проверить provider/ключ")
    elif active_state == "candidate_emitting":
        if timeout_rate > max_timeout_rate:
            blockers.append(f"timeout_rate {round(timeout_rate * 100, 1)}% > {round(max_timeout_rate * 100, 1)}%")
        if provider_error_rate > max_provider_error_rate:
            blockers.append(f"provider_error_rate {round(provider_error_rate * 100, 1)}% > {round(max_provider_error_rate * 100, 1)}%")
        if budget_exhausted_rate > max_budget_exhausted_rate:
            blockers.append(f"budget_exhausted_rate {round(budget_exhausted_rate * 100, 1)}% высок")
        if latency_p95 is not None and latency_p95 > max_avg_latency_p95_ms:
            blockers.append(f"latency {latency_p95}ms > {int(max_avg_latency_p95_ms)}")
        if blockers:
            rollback_recommended = True
            status = "rollback_recommended"
            primary = "rollback_per_channel_stt"
        elif sr_would_attach_rate is not None and sr_would_attach_rate > 0:
            status = "candidate_emit_running"
            primary = "continue_candidate_emit"
        else:
            status = "warning"
            primary = "collect_more_data"
            warnings.append("candidates эмитятся, но source_reconcile не матчит — проверить "
                            "timestamps/text similarity (Stage 13/14)")
    else:
        # shadow_only с per-channel events
        # readiness-гейт зеркалит rollback-блокеры: все rate-пороги + latency + dominance
        ready = (transcribe_success >= min_transcribe_success_count
                 and shadow_suppressed >= min_shadow_suppressed_count
                 and pcs_total >= min_events
                 and timeout_rate <= max_timeout_rate
                 and provider_error_rate <= max_provider_error_rate
                 and budget_exhausted_rate <= max_budget_exhausted_rate
                 and adapter_unavailable_rate <= max_adapter_unavailable_rate
                 and (latency_p95 is None or latency_p95 <= max_avg_latency_p95_ms)
                 and dominance_ok)
        if ready:
            status = "ready_for_candidate_emit"
            primary = "emit_candidates"
            suggested_patch = {
                "audio_per_channel_stt_enabled": True,
                "audio_per_channel_stt_shadow_mode": False,
                "source_reconcile_enabled": True,
                "source_reconcile_shadow_mode": True,
                "source_reconcile_trace_enabled": True,
            }
        elif transcribe_success == 0:
            status = "shadow_collecting"
            if seg_finalized == 0:
                primary = "tighten_vad" if not dominance_ok else "collect_more_data"
                notes.append("0 finalized сегментов — VAD/dominance пороги, возможно, строгие")
            elif timeout_count > 0 or provider_error_count > 0:
                status = "warning"
                primary = "check_provider_latency"
            elif budget_exhausted_count > 0:
                status = "warning"
                primary = "increase_budget"
            else:
                primary = "collect_more_data"
        else:
            status = "shadow_collecting"
            primary = "collect_more_data"

    # VAD/dominance заметка
    if low_dominance_drops > 0 and low_dominance_drops >= max(seg_finalized, 1):
        notes.append("много low_dominance дропов — каналы не изолированы (tighten_vad)")
    if not dominance_ok:
        notes.append(f"средний dominance < {min_avg_dominance_p50} — каналы слабо изолированы")

    rollback_patch = None
    if rollback_recommended:
        from .per_channel_stt_canary_operations import build_per_channel_stt_rollback_patch
        rollback_patch = build_per_channel_stt_rollback_patch()

    per_channel_block = {
        "total": pcs_total,
        "enabled_event_count": enabled_count,
        "max_channels_seen_p50": mc if mc else None,
        "segment_finalized_count": seg_finalized,
        "transcribe_success_count": transcribe_success,
        "candidate_shadow_suppressed_count": shadow_suppressed,
        "candidate_emit_count": candidate_emit,
        "adapter_unavailable_count": adapter_unavailable,
        "api_key_missing_count": api_key_missing_count,
        "timeout_count": timeout_count,
        "provider_error_count": provider_error_count,
        "budget_exhausted_count": budget_exhausted_count,
        "cache_hit_rate": cache_hit_rate,
        "average_dominance_p50": avg_dominance,
        "average_transcribe_latency_p95_ms": latency_p95,
        "by_provider": by_provider,
        "by_last_error_kind": by_last_error_kind,
    }
    source_block = {
        "total": sr_total,
        "would_attach_rate": sr_would_attach_rate,
        "actual_attach_rate": sr_actual_attach_rate,
        "by_match_reason": sr.get("by_match_reason", {}),
    }
    signal_block = {
        "total": se_total,
        "error_rate": (_rate(se_total - se.get("by_error_kind", {}).get("none", 0), se_total)
                       if se_total else None),
        "latency_p95_ms": (se.get("latency_ms") or {}).get("p95"),
    }

    guard_blob = json.dumps({
        "per_channel_stt": per_channel_block, "source_reconciliation": source_block,
        "signal_engine": signal_block, "rollback_patch": rollback_patch, "suggested_patch": suggested_patch,
        "blocking_issues": blockers, "warnings": warnings, "notes": notes,
        "primary_recommendation": primary, "status": status, "active_state": active_state,
    }, ensure_ascii=False)
    safety_checks = {
        "does_not_contain_raw_text": "transcript" not in guard_blob,
        "does_not_contain_raw_source_ids": (
            "audio_source_id" not in guard_blob and "channel_label" not in guard_blob),
        "does_not_contain_raw_speaker_labels": (
            "speaker_label" not in guard_blob and "SM_" not in guard_blob),
        "does_not_contain_segment_ids": (
            "segment_id" not in guard_blob and "candidate_id" not in guard_blob),
        # проверяем реальные индикаторы ключа/заголовка, НЕ слово "api_key" (оно легитимно в
        # имени поля api_key_missing_count и категории error_kind "api_key_missing").
        "does_not_contain_api_key": (
            "xi-api-key" not in guard_blob and "Authorization" not in guard_blob
            and "Bearer " not in guard_blob and "sk_live" not in guard_blob),
        "rollback_patch_only_per_channel_stt": (
            rollback_patch is None
            or all(k.startswith("audio_per_channel_stt_") for k in rollback_patch)),
        "suggested_patch_does_not_enable_source_reconcile_active": (
            suggested_patch is None or suggested_patch.get("source_reconcile_shadow_mode") is not False),
    }

    return {
        "status": status,
        "active_state": active_state,
        "primary_recommendation": primary,
        "rollback_recommended": rollback_recommended,
        "rollback_patch": rollback_patch,
        "blocking_issues": blockers,
        "warnings": warnings,
        "notes": notes,
        "per_channel_stt": per_channel_block,
        "source_reconciliation": source_block,
        "signal_engine": signal_block,
        "suggested_patch": suggested_patch,
        "safety_checks": safety_checks,
    }


# --------------------------------------------------------------------------- CLI

def run_monitor_cli(*, logfile: str, meeting_id: Any = None, session_id: Any = None,
                    check_id: Optional[str] = None, require_single_meeting: bool = False,
                    emit_rollback_if_needed: bool = False) -> int:
    try:
        with open(logfile, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {logfile}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return 2

    loaded = load_per_channel_stt_monitor_events_from_lines(
        lines, meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    report = analyze_per_channel_stt_canary_run(
        per_channel_stt_events=loaded["per_channel_stt"],
        source_reconcile_events=loaded["source_reconcile"],
        signal_engine_events=loaded["signal_engine"])
    report["trace_scope"] = loaded["trace_scope"]
    report["trace_filters"] = loaded["trace_filters"]
    if emit_rollback_if_needed:
        report["apply_rollback"] = report["rollback_recommended"]
        if report["rollback_recommended"]:
            report["rollback_endpoint_template"] = "/api/meetings/{meeting_id}/ai-settings"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if require_single_meeting and report["trace_scope"].get("has_mixed_meetings"):
        return 4
    return 0


def _main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        prog="python -m app.core.context.per_channel_stt_canary_monitor",
        description="Мониторинг per-channel STT canary по одной встрече (--meeting-id).")
    parser.add_argument("logfile")
    parser.add_argument("--meeting-id", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--check-id", default=None)
    parser.add_argument("--require-single-meeting", action="store_true")
    parser.add_argument("--emit-rollback-if-needed", action="store_true")
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3
    return run_monitor_cli(
        logfile=ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id, check_id=ns.check_id,
        require_single_meeting=ns.require_single_meeting,
        emit_rollback_if_needed=ns.emit_rollback_if_needed)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
