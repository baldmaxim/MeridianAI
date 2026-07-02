"""Active Canary Monitor + Rollback Recommendation (Этап 14).

Backend-only мониторинг активной source_reconcile canary-встречи: читает SOURCE_RECONCILE_TRACE +
SIGNAL_ENGINE_TRACE, фильтрует по meeting_id/session_id/check_id (Stage 13), оценивает качество
active attach и выдаёт безопасную рекомендацию (continue/rollback/collect/add hints/tighten/
check timestamps/remain shadow) + готовый rollback patch (НЕ применяет).

Без БД/LLM/network. Вывод — только агрегаты/категории/флаги. Никакого raw text / source ids /
speaker labels / channel ids / segment ids / candidate ids. Сторона — только через
speaker_identity_hints поверх stable link; source/channel = техническая зона записи, не сторона.
"""

import argparse
import json
import sys
from typing import Any, Iterable, Optional

from .canary_operations import ENDPOINT_TEMPLATE, build_source_reconcile_rollback_patch
from .canary_readiness_analysis import extract_all_canary_trace_events_from_lines
from .canary_trace_filter import filter_trace_events, summarize_trace_scope
from .signal_trace_analysis import analyze_signal_traces
from .source_reconcile_trace_analysis import analyze_source_reconcile_traces, percentile

_FORBIDDEN_RAW_TOKENS = (
    "transcript", "speaker_label", "audio_source_id", "channel_label",
    "segment_id", "candidate_id", "SM_", "Speaker ",
)


def _rate(num: float, den: float) -> float:
    return round(num / den, 4) if den else 0.0


def _matched_pctl(events: list[dict], field: str, p: float) -> Optional[float]:
    """Перцентиль field по would-attach событиям (match quality), а не по всем попыткам.

    Важно: rejected/no_candidates пишут match_score/overlap/similarity=0.0 в trace; перцентиль по
    ВСЕМ событиям занижался бы законно отклонёнными сегментами. Здоровье attach считаем по
    would_attach_without_shadow population.
    """
    vals = [float(e[field]) for e in events
            if e.get("would_attach_without_shadow") and isinstance(e.get(field), (int, float))]
    v = percentile(vals, p)
    return None if v is None else round(v, 4)


def load_canary_monitor_events_from_lines(
    lines: Iterable[str],
    *,
    meeting_id: Any = None,
    session_id: Any = None,
    check_id: Optional[str] = None,
) -> dict:
    """Извлечь и отфильтровать оба потока trace + безопасный scope/filters."""
    ev = extract_all_canary_trace_events_from_lines(lines)
    sr_f, sr_stats = filter_trace_events(
        ev["source_reconcile"], meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    se_f, se_stats = filter_trace_events(
        ev["signal_engine"], meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    pre_scope = summarize_trace_scope(
        source_reconcile_events=ev["source_reconcile"], signal_engine_events=ev["signal_engine"])
    return {
        "source_reconcile": sr_f,
        "signal_engine": se_f,
        "trace_scope": summarize_trace_scope(
            source_reconcile_events=sr_f, signal_engine_events=se_f),
        "trace_filters": {
            "filters_applied": sr_stats["filters_applied"],
            "filter_hashes": sr_stats["filter_hashes"],
            "source_reconcile": {
                "input_count": sr_stats["input_count"], "output_count": sr_stats["output_count"]},
            "signal_engine": {
                "input_count": se_stats["input_count"], "output_count": se_stats["output_count"]},
            "pre_filter_has_mixed_meetings": pre_scope["has_mixed_meetings"],
        },
    }


def analyze_active_canary_run(
    *,
    source_reconcile_events: list[dict],
    signal_engine_events: list[dict],
    min_source_events: int = 10,
    max_safe_actual_attach_rate: float = 0.25,
    max_ambiguous_rate: float = 0.10,
    max_low_overlap_rate: float = 0.25,
    max_low_similarity_rate: float = 0.25,
    min_score_p50: float = 0.65,
    max_unknown_side_event_rate: float = 0.50,
    min_hint_source_event_rate: float = 0.20,
    max_signal_error_rate: float = 0.05,
    max_signal_latency_p95_ms: float = 5000.0,
) -> dict:
    """Безопасный отчёт о здоровье active canary + рекомендация. Только агрегаты."""
    sr = analyze_source_reconcile_traces(source_reconcile_events)
    se = analyze_signal_traces(signal_engine_events)

    total = sr["total"]
    se_total = se["total"]
    would = sr["would_attach_count"]
    actual = sr["actual_attach_count"]
    by_match = sr.get("by_match_reason", {})

    amb_rate = _rate(by_match.get("ambiguous", 0), total)
    lo_rate = _rate(by_match.get("low_overlap", 0), total)
    ls_rate = _rate(by_match.get("low_text_similarity", 0), total)
    nc_rate = _rate(by_match.get("no_candidates", 0), total)
    # match-quality перцентили — по would-attach population, не по всем попыткам (см. _matched_pctl)
    score_p50 = _matched_pctl(source_reconcile_events, "match_score", 50)
    score_p90 = _matched_pctl(source_reconcile_events, "match_score", 90)
    overlap_p50 = _matched_pctl(source_reconcile_events, "time_overlap", 50)
    sim_p50 = _matched_pctl(source_reconcile_events, "text_similarity", 50)
    actual_rate = sr.get("actual_attach_rate") or 0.0
    would_rate = sr.get("would_attach_rate") or 0.0
    ratio = round(actual / would, 4) if would else None

    sc = se.get("speaker_context") if isinstance(se.get("speaker_context"), dict) else {}
    unk = sc.get("unknown_side_event_rate")
    hint = sc.get("hint_source_event_rate")
    audio = sc.get("audio_linked_event_rate")

    by_error = se.get("by_error_kind", {})
    te_rate = _rate(by_error.get("timeout", 0) + by_error.get("exception", 0), se_total) if se_total else None
    err_rate = _rate(se_total - by_error.get("none", 0), se_total) if se_total else None
    lat_p95 = (se.get("latency_ms") or {}).get("p95")

    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    rollback_recommended = False

    # --- Signal Engine warnings (информационные; сами по себе rollback не триггерят) ---
    if se_total:
        if te_rate is not None and te_rate > max_signal_error_rate:
            warnings.append(f"Signal Engine timeout/exception {round(te_rate * 100, 1)}% — проверить LLM/timeout")
        if lat_p95 is not None and lat_p95 > max_signal_latency_p95_ms:
            warnings.append(f"Signal Engine latency p95 = {lat_p95}ms > {int(max_signal_latency_p95_ms)}")

    # --- Speaker hint coverage warnings ---
    low_hint_coverage = (
        unk is not None and unk > max_unknown_side_event_rate
        and hint is not None and hint < min_hint_source_event_rate)
    if low_hint_coverage:
        warnings.append("source links may exist, but speaker_identity_hints coverage is low")
    if audio is not None and audio > 0.5 and unk is not None and unk > 0.5:
        warnings.append("audio links есть, но hints не покрывают sources/channels")
    severe_speaker = (
        unk is not None and unk > 0.7 and hint is not None and hint < 0.2
        and audio is not None and audio > 0.5)

    # --- active_state ---
    if total == 0:
        active_state = "no_reconcile"
    elif actual > 0:
        active_state = "active_attaching"
    else:
        active_state = "shadow_only"

    # --- основной разбор ---
    if total == 0 and se_total == 0:
        status = "no_data"
        primary = "remain_in_shadow"
        blockers.append("нет trace events (SOURCE_RECONCILE_TRACE/SIGNAL_ENGINE_TRACE)")
    elif total == 0:
        status = "shadow_only"
        primary = "remain_in_shadow"
        warnings.append("нет SOURCE_RECONCILE_TRACE; проверить multi_channel_live/source_reconcile trace collection")
    elif actual == 0:
        # reconcile есть, но live attach не происходит → rollback не нужен
        if would > 0:
            status = "shadow_only"
            primary = "remain_in_shadow"
            notes.append("shadow считает would_attach, но active не включён (shadow_mode=true)")
        else:
            # would==0: primary по доминирующей причине (priority), но в notes — ВСЕ повышенные
            if nc_rate > 0.5:
                status = "collecting"
                primary = "collect_more_data"
            elif lo_rate > max_low_overlap_rate:
                status = "warning"
                primary = "check_multichannel_timestamps"
            elif ls_rate > max_low_similarity_rate:
                status = "warning"
                primary = "tighten_thresholds"
            elif amb_rate > max_ambiguous_rate:
                status = "warning"
                primary = "tighten_thresholds"
            else:
                status = "collecting"
                primary = "collect_more_data"
            # co-occurring failure modes — surface все повышенные match reasons, не только primary
            if nc_rate > 0.5:
                notes.append("много no_candidates — нет source candidates (multi_channel_live/secondary)")
            if lo_rate > max_low_overlap_rate:
                notes.append(f"low_overlap_rate {round(lo_rate * 100, 1)}% — проверить timestamp-шкалы каналов")
            if ls_rate > max_low_similarity_rate:
                notes.append(f"low_text_similarity_rate {round(ls_rate * 100, 1)}% — расходятся transcripts")
            if amb_rate > max_ambiguous_rate:
                notes.append(f"ambiguous_rate {round(amb_rate * 100, 1)}% — снизить overlap window/улучшить timestamps")
    else:
        # actual > 0 → active attaching: оцениваем деградацию
        if amb_rate > max_ambiguous_rate:
            blockers.append(f"ambiguous_rate {round(amb_rate * 100, 1)}% > {round(max_ambiguous_rate * 100, 1)}%")
        if lo_rate > max_low_overlap_rate:
            blockers.append(f"low_overlap_rate {round(lo_rate * 100, 1)}% > {round(max_low_overlap_rate * 100, 1)}%")
        if ls_rate > max_low_similarity_rate:
            blockers.append(f"low_text_similarity_rate {round(ls_rate * 100, 1)}% > {round(max_low_similarity_rate * 100, 1)}%")
        if score_p50 is not None and score_p50 < min_score_p50:
            blockers.append(f"score_p50 {score_p50} < {min_score_p50}")
        if actual_rate > max_safe_actual_attach_rate:
            blockers.append(f"actual_attach_rate {actual_rate} > {max_safe_actual_attach_rate}")
        # severe speaker degradation (unknown>70%, hints<20%, audio high): пропорциональная реакция —
        # rollback только если attach «слишком активен» (это уже покрыто blocker'ом actual_attach_rate
        # выше); при низком attach rate — add_speaker_identity_hints (см. elif ниже), не rollback.

        if blockers:
            rollback_recommended = True
            status = "rollback_recommended"
            primary = "rollback_source_reconcile"
        elif total < min_source_events:
            status = "collecting"
            primary = "collect_more_data"
            notes.append(f"мало source events ({total} < {min_source_events}) — собрать больше перед выводами")
        elif low_hint_coverage or severe_speaker:
            status = "warning"
            primary = "add_speaker_identity_hints"
        else:
            status = "healthy"
            primary = "continue_active"

    rollback_patch = build_source_reconcile_rollback_patch() if rollback_recommended else None

    source_block = {
        "total": total,
        "would_attach_count": would,
        "actual_attach_count": actual,
        "would_attach_rate": would_rate,
        "actual_attach_rate": actual_rate,
        "actual_to_would_ratio": ratio,
        "by_decision_reason": sr.get("by_decision_reason", {}),
        "by_match_reason": by_match,
        "score_p50": score_p50,
        "score_p90": score_p90,
        "time_overlap_p50": overlap_p50,
        "text_similarity_p50": sim_p50,
        "ambiguous_rate": amb_rate,
        "low_overlap_rate": lo_rate,
        "low_text_similarity_rate": ls_rate,
    }
    speaker_block = {
        "signal_events": se_total,
        "unknown_side_event_rate": unk,
        "hint_source_event_rate": hint,
        "audio_linked_event_rate": audio,
        "avg_speaker_confidence_p50": sc.get("avg_speaker_confidence_p50"),
    }
    signal_block = {
        "total": se_total,
        "error_rate": err_rate,
        "timeout_exception_rate": te_rate,
        "latency_p95_ms": lat_p95,
        "would_prompt_rate": se.get("would_prompt_rate"),
        "actual_prompt_rate": se.get("actual_prompt_rate"),
        "by_error_kind": by_error,
        "by_decision_reason": se.get("by_decision_reason", {}),
    }

    # safety: guard по data-частям (без schema-полей safety_checks, чьи имена содержат слова-маркеры)
    guard_blob = json.dumps({
        "source_reconciliation": source_block,
        "speaker_context": speaker_block,
        "signal_engine": signal_block,
        "rollback_patch": rollback_patch,
        "blocking_issues": blockers,
        "warnings": warnings,
        "notes": notes,
        "primary_recommendation": primary,
        "status": status,
        "active_state": active_state,
    }, ensure_ascii=False)
    safety_checks = {
        "does_not_contain_raw_text": "transcript" not in guard_blob,
        "does_not_contain_raw_source_ids": (
            "audio_source_id" not in guard_blob and "channel_label" not in guard_blob),
        "does_not_contain_raw_speaker_labels": (
            "speaker_label" not in guard_blob and "SM_" not in guard_blob),
        "does_not_contain_segment_ids": (
            "segment_id" not in guard_blob and "candidate_id" not in guard_blob),
        "rollback_patch_only_source_reconcile": (
            rollback_patch is None
            or all(k.startswith("source_reconcile_") for k in rollback_patch)),
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
        "source_reconciliation": source_block,
        "speaker_context": speaker_block,
        "signal_engine": signal_block,
        "safety_checks": safety_checks,
    }


# --------------------------------------------------------------------------- CLI

def run_monitor_cli(
    *,
    logfile: str,
    meeting_id: Any = None,
    session_id: Any = None,
    check_id: Optional[str] = None,
    require_single_meeting: bool = False,
    emit_rollback_if_needed: bool = False,
) -> int:
    """Общая CLI-логика монитора (используется обоими модулями-CLI). Возвращает exit code."""
    try:
        with open(logfile, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {logfile}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return 2

    loaded = load_canary_monitor_events_from_lines(
        lines, meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    report = analyze_active_canary_run(
        source_reconcile_events=loaded["source_reconcile"],
        signal_engine_events=loaded["signal_engine"])
    report["trace_scope"] = loaded["trace_scope"]
    report["trace_filters"] = loaded["trace_filters"]

    if emit_rollback_if_needed:
        report["apply_rollback"] = report["rollback_recommended"]
        if report["rollback_recommended"]:
            report["rollback_endpoint_template"] = ENDPOINT_TEMPLATE

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
        prog="python -m app.core.context.active_canary_monitor",
        description="Мониторинг active source_reconcile canary по одной встрече (--meeting-id).")
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
        logfile=ns.logfile, meeting_id=ns.meeting_id, session_id=ns.session_id,
        check_id=ns.check_id, require_single_meeting=ns.require_single_meeting,
        emit_rollback_if_needed=ns.emit_rollback_if_needed)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
