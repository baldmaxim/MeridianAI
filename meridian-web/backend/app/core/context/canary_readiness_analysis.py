"""Combined canary readiness analyzer (Этап 12).

Читает реальные логи (SOURCE_RECONCILE_TRACE + SIGNAL_ENGINE_TRACE), переиспользует существующие
парсеры/анализаторы и выдаёт единый readiness-вердикт + blockers/warnings + suggested_patch.

Вывод — только агрегаты (которые уже безопасны в trace): никаких raw text / source ids / speaker
labels / segment ids / raw trace lines. Без БД/LLM/network.
"""

import argparse
import json
import sys
from typing import Any, Iterable, Optional

from .canary_trace_filter import filter_trace_events, summarize_trace_scope
from .signal_trace_analysis import analyze_signal_traces, extract_trace_json_from_line
from .source_reconcile_trace_analysis import (
    analyze_source_reconcile_traces,
    extract_source_reconcile_json_from_line,
)


def extract_all_canary_trace_events_from_lines(lines: Iterable[str]) -> dict:
    """Один проход по логам: разнести SOURCE_RECONCILE_TRACE и SIGNAL_ENGINE_TRACE."""
    sr: list[dict] = []
    se: list[dict] = []
    for line in lines:
        rc = extract_source_reconcile_json_from_line(line)
        if rc is not None:
            sr.append(rc)
            continue
        sig = extract_trace_json_from_line(line)
        if sig is not None:
            se.append(sig)
    return {"source_reconcile": sr, "signal_engine": se}


def _frac(d: dict, key: str, total: int) -> float:
    return (d.get(key, 0) / total) if total else 0.0


def analyze_canary_readiness(
    *, source_reconcile_events: list[dict], signal_engine_events: list[dict],
) -> dict:
    """Единый readiness-отчёт. Только безопасные агрегаты."""
    sr = analyze_source_reconcile_traces(source_reconcile_events)
    se = analyze_signal_traces(signal_engine_events)
    sr_total = sr["total"]
    se_total = se["total"]

    sc = se.get("speaker_context", {}) if isinstance(se.get("speaker_context"), dict) else {}
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    suggested_patch: Optional[dict] = None

    # --- speaker_context warnings (Signal Engine граф) ---
    unk_rate = sc.get("unknown_side_event_rate")
    hint_rate = sc.get("hint_source_event_rate")
    audio_rate = sc.get("audio_linked_event_rate")
    if unk_rate is not None and unk_rate > 0.5 and hint_rate is not None and hint_rate < 0.2:
        warnings.append("source reconciliation может работать, но покрытие speaker_identity_hints низкое")
    if audio_rate is not None and audio_rate > 0.5 and unk_rate is not None and unk_rate > 0.5:
        warnings.append("audio/channel links есть, но hints не покрывают sources/channels")

    # --- signal engine warnings ---
    if se_total:
        by_err = se.get("by_error_kind", {})
        err_rate = (by_err.get("timeout", 0) + by_err.get("exception", 0)) / se_total
        if err_rate > 0.05:
            warnings.append(f"Signal Engine timeout/exception {round(err_rate * 100, 1)}% — проверить LLM/timeout")
        lat_p95 = (se.get("latency_ms") or {}).get("p95")
        if lat_p95 is not None and lat_p95 > 5000:
            warnings.append(f"Signal Engine latency p95 = {lat_p95}ms > 5000")
        wpr = se.get("would_prompt_rate")
        if wpr is not None and wpr > 0.2:
            warnings.append("Signal Engine would_prompt_rate > 20% — возможно слишком часто")

    # --- verdict по source reconcile ---
    score_p50 = (sr.get("score") or {}).get("p50")
    if sr_total == 0 and se_total == 0:
        verdict = "no_data"
        blockers.append("нет trace events (SOURCE_RECONCILE_TRACE/SIGNAL_ENGINE_TRACE)")
        rec = "собрать trace: включить логи на встречах и повторить анализ"
    elif sr_total == 0:
        verdict = "ready_for_shadow_collection"
        rec = "включить/проверить multi_channel_live и сбор SOURCE_RECONCILE_TRACE (shadow)"
    else:
        # blockers по match reasons
        if _frac(sr["by_match_reason"], "no_candidates", sr_total) > 0.5:
            blockers.append("много no_candidates — нет source candidates")
        if _frac(sr["by_match_reason"], "low_overlap", sr_total) > 0.25:
            blockers.append("low_overlap > 25% — проверить timestamp шкалы")
        if _frac(sr["by_match_reason"], "low_text_similarity", sr_total) > 0.25:
            blockers.append("low_text_similarity > 25% — проверить расхождение transcripts")
        if _frac(sr["by_match_reason"], "ambiguous", sr_total) > 0.1:
            blockers.append("ambiguous source matches > 10%")
        if sr["would_attach_count"] > 0 and score_p50 is not None and score_p50 < 0.65:
            blockers.append("низкий match score p50 < 0.65")
        if sr["would_attach_rate"] is not None and sr["would_attach_rate"] > 0.25:
            warnings.append("would_attach_rate > 25% — thresholds могут быть мягкими")

        if sr["actual_attach_count"] > 0:
            verdict = "active_canary_running"
            rec = "мониторить actual_attach + unknown_side_event_rate; не расширять без проверки"
        elif sr["would_attach_count"] == 0 or blockers:
            verdict = "not_ready"
            if not blockers:
                blockers.append("would_attach_rate=0 — нет успешных matches")
            rec = "устранить blockers (timestamps/transcripts/candidates), собрать ещё shadow trace"
        else:
            verdict = "ready_for_active_source_reconcile_canary"
            cutoff = None
            for tc in sr.get("threshold_candidates", []):
                if tc.get("target_rate") == 0.05:
                    cutoff = tc.get("score_cutoff")
            suggested_patch = {
                "source_reconcile_enabled": True,
                "source_reconcile_shadow_mode": False,
                "source_reconcile_min_text_similarity": 0.78,
                "source_reconcile_min_time_overlap": 0.45,
                "source_reconcile_min_match_score": max(0.62, round(cutoff, 4)) if cutoff is not None else 0.62,
                "source_reconcile_ambiguity_margin": 0.08,
            }
            rec = "применить suggested_patch на ОДНОЙ канареечной встрече (source_reconcile_shadow_mode=false)"

    return {
        "verdict": verdict,
        "blocking_issues": blockers,
        "warnings": warnings,
        "recommended_next_action": rec,
        "source_reconciliation": {
            "total": sr_total,
            "would_attach_rate": sr.get("would_attach_rate"),
            "actual_attach_rate": sr.get("actual_attach_rate"),
            "by_decision_reason": sr.get("by_decision_reason", {}),
            "by_match_reason": sr.get("by_match_reason", {}),
            "score_p50": (sr.get("score") or {}).get("p50"),
            "score_p90": (sr.get("score") or {}).get("p90"),
            "time_overlap_p50": (sr.get("time_overlap") or {}).get("p50"),
            "text_similarity_p50": (sr.get("text_similarity") or {}).get("p50"),
        },
        "speaker_context": {
            "signal_events": se_total,
            "unknown_side_event_rate": sc.get("unknown_side_event_rate"),
            "hint_source_event_rate": sc.get("hint_source_event_rate"),
            "audio_linked_event_rate": sc.get("audio_linked_event_rate"),
            "avg_speaker_confidence_p50": sc.get("avg_speaker_confidence_p50"),
        },
        "signal_engine": {
            "total": se_total,
            "would_prompt_rate": se.get("would_prompt_rate"),
            "actual_prompt_rate": se.get("actual_prompt_rate"),
            "by_error_kind": se.get("by_error_kind", {}),
            "by_decision_reason": se.get("by_decision_reason", {}),
            "latency_p95_ms": (se.get("latency_ms") or {}).get("p95"),
        },
        "suggested_patch": suggested_patch,
        "notes": notes,
    }


def analyze_canary_readiness_from_events(
    *,
    source_reconcile_events: list[dict],
    signal_engine_events: list[dict],
    meeting_id: Any = None,
    session_id: Any = None,
    check_id: Optional[str] = None,
) -> dict:
    """Как analyze_canary_readiness, но сначала режет events по meeting/session/check_id.

    Защита от смешанных встреч: если в логе несколько meeting_id, а meeting_id не задан —
    добавляется warning. В отчёт добавляются безопасные `trace_scope` (counts/флаги, без raw id)
    и `trace_filters` (filters_applied + filter_hashes + counts before/after).
    """
    pre_scope = summarize_trace_scope(
        source_reconcile_events=source_reconcile_events, signal_engine_events=signal_engine_events)
    sr_f, sr_stats = filter_trace_events(
        source_reconcile_events, meeting_id=meeting_id, session_id=session_id, check_id=check_id)
    se_f, se_stats = filter_trace_events(
        signal_engine_events, meeting_id=meeting_id, session_id=session_id, check_id=check_id)

    report = analyze_canary_readiness(source_reconcile_events=sr_f, signal_engine_events=se_f)

    if pre_scope["has_mixed_meetings"] and meeting_id is None:
        report.setdefault("warnings", []).append(
            "лог содержит несколько meeting_id — readiness лучше считать по одной встрече (--meeting-id)")

    report["trace_scope"] = summarize_trace_scope(
        source_reconcile_events=sr_f, signal_engine_events=se_f)
    report["trace_filters"] = {
        "filters_applied": sr_stats["filters_applied"],
        "filter_hashes": sr_stats["filter_hashes"],
        "source_reconcile": {
            "input_count": sr_stats["input_count"], "output_count": sr_stats["output_count"]},
        "signal_engine": {
            "input_count": se_stats["input_count"], "output_count": se_stats["output_count"]},
    }
    return report


def _read_log_lines(path: str) -> Optional[list[str]]:
    """Прочитать файл лога; None при отсутствии/ошибке чтения (вызывающий → exit 2)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {path}", file=sys.stderr)
        return None
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return None


def _main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        prog="python -m app.core.context.canary_readiness_analysis",
        description="Readiness-анализ canary trace (по одной встрече при --meeting-id).")
    parser.add_argument("logfile", help="путь к app.log с SOURCE_RECONCILE_TRACE/SIGNAL_ENGINE_TRACE")
    parser.add_argument("--meeting-id", default=None, help="фильтр по meeting_id")
    parser.add_argument("--session-id", default=None, help="фильтр по session_id")
    parser.add_argument("--check-id", default=None, help="фильтр по check_id")
    parser.add_argument("--require-single-meeting", action="store_true",
                        help="exit 4, если лог содержит несколько meeting_id без фильтра")
    try:
        ns = parser.parse_args(argv[1:])
    except SystemExit:
        return 3

    lines = _read_log_lines(ns.logfile)
    if lines is None:
        return 2

    ev = extract_all_canary_trace_events_from_lines(lines)
    summary = analyze_canary_readiness_from_events(
        source_reconcile_events=ev["source_reconcile"], signal_engine_events=ev["signal_engine"],
        meeting_id=ns.meeting_id, session_id=ns.session_id, check_id=ns.check_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if ns.require_single_meeting and summary.get("trace_scope", {}).get("has_mixed_meetings"):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
