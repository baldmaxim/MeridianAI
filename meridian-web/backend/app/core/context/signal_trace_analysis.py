"""Offline-анализатор логов SIGNAL_ENGINE_TRACE (Этап 3) — без pandas и внешних зависимостей.

Парсит строки `SIGNAL_ENGINE_TRACE {json}`, считает агрегаты для калибровки порогов.
Не меняет runtime policy — это только отчёт. Trace по умолчанию не содержит текста
переговоров, поэтому анализатор работает с длинами/hash/агрегатами.

CLI:
    python -m app.core.context.signal_trace_analysis path/to/logfile.log
"""

import json
import math
import sys
from collections import Counter
from typing import Iterable, Optional

_MARKER = "SIGNAL_ENGINE_TRACE"
_TARGET_RATES = (0.02, 0.05, 0.10)


def _first_balanced_object(text: str) -> Optional[str]:
    """Вернуть подстроку первого сбалансированного {...} (учёт строк/escape)."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract_trace_json_from_line(line: str) -> Optional[dict]:
    """Найти маркер SIGNAL_ENGINE_TRACE и распарсить следующий за ним JSON-объект."""
    if not line or _MARKER not in line:
        return None
    after = line.split(_MARKER, 1)[1]
    snippet = _first_balanced_object(after)
    if snippet is None:
        return None
    try:
        obj = json.loads(snippet)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def load_trace_events_from_lines(lines: Iterable[str]) -> list[dict]:
    """Распарсить все строки логов в список trace-событий (битые/без маркера игнорируются)."""
    events: list[dict] = []
    for line in lines:
        obj = extract_trace_json_from_line(line)
        if obj is not None:
            events.append(obj)
    return events


def percentile(values: list[float], p: float) -> Optional[float]:
    """Линейно-интерполированный перцентиль (p: 0..100). None для пустого списка."""
    if not values:
        return None
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return xs[int(k)]
    return xs[lo] * (hi - k) + xs[hi] * (k - lo)


def _round(v: Optional[float], n: int = 4) -> Optional[float]:
    return None if v is None else round(v, n)


def _sum_field(events: list[dict], field: str) -> int:
    return sum(int(e[field]) for e in events if isinstance(e.get(field), (int, float)))


def _threshold_candidates(scored: list[float]) -> list[dict]:
    """Кандидаты score-cutoff под целевые prompt rates (только отчёт, не меняет policy)."""
    out: list[dict] = []
    n = len(scored)
    for r in _TARGET_RATES:
        if n == 0:
            out.append({"target_rate": r, "score_cutoff": None,
                        "estimated_prompt_rate": 0.0,
                        "comment": "нет событий с error_kind=none"})
            continue
        cutoff = percentile(scored, (1.0 - r) * 100.0)
        kept = sum(1 for s in scored if s >= cutoff)
        est = kept / n
        out.append({
            "target_rate": r,
            "score_cutoff": _round(cutoff),
            "estimated_prompt_rate": _round(est),
            "comment": f"score>={_round(cutoff)} -> ~{round(est * 100, 1)}% подсказок (по {n} событиям)",
        })
    return out


def analyze_signal_traces(events: list[dict]) -> dict:
    """Сводка по trace-событиям для калибровки порогов."""
    total = len(events)
    if total == 0:
        return {
            "total": 0, "would_prompt_count": 0, "actual_prompt_count": 0,
            "would_prompt_rate": 0.0, "actual_prompt_rate": 0.0,
            "by_decision_reason": {}, "by_error_kind": {}, "by_situation_type": {},
            "top_novelty_keys": [], "score": {}, "latency_ms": {},
            "threshold_candidates": _threshold_candidates([]),
            "speaker_context": {
                "events_with_speaker_context": 0, "avg_speaker_confidence_p50": None,
                "unknown_side_event_rate": None, "by_source": {},
                "speaker_count_p50": None, "unknown_side_count_p50": None,
                "hint_source_count_p50": None, "hint_source_event_rate": None,
                "audio_linked_event_rate": None, "audio_linked_count_p50": None,
                "channel_linked_count_p50": None, "audio_link_confidence_p50": None,
                "by_audio_link_source": {},
                "attribution_observation_count_p50": None, "attribution_stable_link_count_p50": None,
                "attribution_ambiguous_count_p50": None, "attribution_average_confidence_p50": None,
                "attribution_source_event_rate": None, "by_attribution_source": {},
            },
            "source_reconciliation": {
                "candidate_count_p50": None, "match_count_p50": None, "match_rate": None,
                "ambiguous_count_p50": None, "rejected_count_p50": None,
                "average_match_score_p50": None, "by_candidate_source": {}, "by_match_reason": {},
            },
            "audio_capture": {
                "events_with_audio_capture": 0, "by_route": {}, "by_pipeline": {},
                "by_source_kind": {}, "actual_channel_count_p50": None, "actual_sample_rate_p50": None,
            },
            "audio_multichannel": {
                "events_with_multichannel": 0, "frame_count_p50": None, "max_channels_seen_p50": None,
                "parse_error_count_p50": None, "sequence_gap_count_p50": None,
                "clipping_event_count_p50": None,
            },
            "audio_per_channel_stt": {
                "events_enabled": 0, "segment_finalized_p50": None, "transcribe_success_p50": None,
                "candidate_emit_p50": None, "shadow_suppressed_p50": None, "average_dominance_p50": None,
            },
            "notes": ["нет событий SIGNAL_ENGINE_TRACE"],
        }

    would_prompt_count = sum(1 for e in events if e.get("would_prompt_without_shadow"))
    actual_prompt_count = sum(1 for e in events if e.get("actual_should_prompt"))
    would_prompt_rate = would_prompt_count / total
    actual_prompt_rate = actual_prompt_count / total

    by_reason = Counter(str(e.get("decision_reason", "unknown")) for e in events)
    by_error = Counter(str(e.get("error_kind", "none")) for e in events)
    by_situation = Counter(str(e.get("situation_type", "none")) for e in events)

    novelty_counter = Counter(
        str(e.get("novelty_key", "none"))
        for e in events
        if e.get("would_prompt_without_shadow") and e.get("novelty_key") not in (None, "none")
    )
    top_novelty = [{"key": k, "count": c} for k, c in novelty_counter.most_common(10)]

    scored = [float(e["score"]) for e in events
              if e.get("error_kind", "none") == "none" and isinstance(e.get("score"), (int, float))]
    score_summary = {
        "p50": _round(percentile(scored, 50)),
        "p75": _round(percentile(scored, 75)),
        "p90": _round(percentile(scored, 90)),
        "p95": _round(percentile(scored, 95)),
    }

    latencies = [float(e["latency_ms"]) for e in events
                 if isinstance(e.get("latency_ms"), (int, float))]
    latency_summary = {
        "p50": _round(percentile(latencies, 50), 1),
        "p90": _round(percentile(latencies, 90), 1),
        "p95": _round(percentile(latencies, 95), 1),
    }

    notes: list[str] = []
    err_rate = (by_error.get("timeout", 0) + by_error.get("exception", 0)) / total
    if err_rate > 0.05:
        notes.append(f"высокая доля timeout/exception ({round(err_rate * 100, 1)}%) — проверить LLM/timeout")
    if total and by_reason.get("shadow_mode", 0) / total > 0.20:
        notes.append("decision_reason=shadow_mode > 20% — возможны слишком частые подсказки")
    if would_prompt_rate < 0.02:
        notes.append("would_prompt_rate < 2% — возможны слишком строгие пороги или слабый Signal Engine prompt")
    lat_p95 = latency_summary.get("p95")
    if lat_p95 is not None and lat_p95 > 5000:
        notes.append(f"latency p95 = {lat_p95}ms > 5000 — проверить timeout/model latency")
    if would_prompt_count and top_novelty:
        share = top_novelty[0]["count"] / would_prompt_count
        if share > 0.30:
            notes.append(f"top novelty_key занимает {round(share * 100, 1)}% would_prompt — возможны дубли одного типа сигнала")

    speaker_summary = _speaker_context_summary(events)
    unk_rate = speaker_summary["unknown_side_event_rate"]
    if unk_rate is not None and unk_rate > 0.5:
        notes.append("более 50% событий имеют unknown speaker side — нужно улучшить role assignment")
    avg_conf_p50 = speaker_summary["avg_speaker_confidence_p50"]
    if avg_conf_p50 is not None and avg_conf_p50 < 0.6:
        notes.append("низкая уверенность speaker graph — Signal Engine может ошибаться адресатом")
    hint_rate = speaker_summary["hint_source_event_rate"]
    if speaker_summary["events_with_speaker_context"] > 0 and hint_rate is not None and hint_rate < 0.2:
        notes.append("мало явных speaker hints — роли в основном неизвестны или из transcript labels")
    audio_rate = speaker_summary["audio_linked_event_rate"]
    if (hint_rate is not None and hint_rate < 0.2
            and audio_rate is not None and audio_rate < 0.2):
        notes.append("мало speaker hints и audio/channel links — роли будут часто unknown")
    if (audio_rate is not None and audio_rate > 0.5
            and unk_rate is not None and unk_rate > 0.5):
        notes.append("audio/channel links есть, но hints не покрывают sources/channels")
    audio_conf_p50 = speaker_summary["audio_link_confidence_p50"]
    if audio_conf_p50 is not None and audio_conf_p50 < 0.5:
        notes.append("низкая уверенность audio/channel links")
    obs_p50 = speaker_summary["attribution_observation_count_p50"]
    link_p50 = speaker_summary["attribution_stable_link_count_p50"]
    amb_p50 = speaker_summary["attribution_ambiguous_count_p50"]
    attr_rate = speaker_summary["attribution_source_event_rate"]
    if obs_p50 is not None and obs_p50 > 0 and link_p50 is not None and link_p50 == 0:
        notes.append("есть audio attribution observations, но нет stable links — проверить "
                     "dominance/confidence thresholds или качество source metadata")
    if amb_p50 is not None and amb_p50 > 0:
        notes.append("часть speaker labels неоднозначно связана с несколькими sources/channels")
    if (attr_rate is not None and attr_rate < 0.2
            and unk_rate is not None and unk_rate > 0.5):
        notes.append("мало live audio attribution — speaker sides будут часто unknown")

    reconcile_summary = _source_reconciliation_summary(events)
    rc_cand_p50 = reconcile_summary["candidate_count_p50"]
    rc_match_p50 = reconcile_summary["match_count_p50"]
    rc_amb_p50 = reconcile_summary["ambiguous_count_p50"]
    rc_rate = reconcile_summary["match_rate"]
    rc_score_p50 = reconcile_summary["average_match_score_p50"]
    if rc_cand_p50 is not None and rc_cand_p50 > 0 and rc_match_p50 is not None and rc_match_p50 == 0:
        notes.append("есть source candidates, но нет matches — проверить timestamps/text "
                     "similarity/candidate confidence")
    if rc_amb_p50 is not None and rc_amb_p50 > 0:
        notes.append("есть ambiguous source attribution matches — снизить overlap window или "
                     "улучшить timestamps")
    if (rc_rate is not None and rc_rate > 0.5 and unk_rate is not None and unk_rate > 0.5):
        notes.append("source reconciliation работает, но speaker_identity_hints не покрывают "
                     "sources/channels")
    if rc_score_p50 is not None and rc_score_p50 < 0.65:
        notes.append("низкий score source reconciliation — не расширять rollout без проверки")

    audio_capture_summary = _audio_capture_summary(events)
    ac_with = audio_capture_summary["events_with_audio_capture"]
    usb_like = (audio_capture_summary["by_route"].get("usb_recorder", 0)
                + audio_capture_summary["by_route"].get("usb_room_mic", 0))
    if ac_with > 0:
        by_route = audio_capture_summary["by_route"]
        laptop_like = by_route.get("laptop_mic", 0) + by_route.get("browser_default", 0)
        if laptop_like / ac_with > 0.5:
            notes.append("audio route в основном laptop/default mic — для canary рассмотреть "
                         "USB speakerphone/recorder")

    audio_multichannel_summary = _audio_multichannel_summary(events)
    mc_with = audio_multichannel_summary["events_with_multichannel"]
    mc_max_ch = audio_multichannel_summary["max_channels_seen_p50"]
    if usb_like > 0 and mc_with == 0:
        notes.append("USB route выбран, но v2 multichannel shadow frames не приходят — проверить "
                     "frontend opt-in / поддержку каналов браузером")
    if mc_max_ch is not None and mc_max_ch >= 2:
        notes.append("multichannel shadow видит 2+ канала — кандидат на Stage 17 per-channel STT")
    if (audio_multichannel_summary["parse_error_count_p50"] or 0) > 0:
        notes.append("v2 frame parse errors — проверить совместимость протокола")
    if (audio_multichannel_summary["sequence_gap_count_p50"] or 0) >= 5:
        notes.append("v2 frame drops/backpressure (sequence gaps)")

    pcs_summary = _audio_per_channel_stt_summary(events)
    pcs_enabled = pcs_summary["events_enabled"]
    pcs_candidate_emit = _sum_field(events, "audio_per_channel_stt_candidate_emit_count")
    pcs_shadow_suppressed = _sum_field(events, "audio_per_channel_stt_candidate_shadow_suppressed_count")
    sr_would_attach = _sum_field(events, "source_reconcile_would_attach_count")
    if mc_max_ch is not None and mc_max_ch >= 2 and pcs_enabled == 0:
        notes.append("multichannel готов (2+ канала), но per-channel STT canary выключен — включить, "
                     "чтобы получать source candidates")
    if pcs_shadow_suppressed > 0 and pcs_candidate_emit == 0:
        notes.append("per-channel STT shadow генерирует кандидатов — снять per-channel shadow, чтобы "
                     "кормить source reconciler")
    if pcs_candidate_emit > 0 and sr_would_attach == 0:
        notes.append("candidates есть, но source reconciliation не матчит — проверить timestamps/text similarity")
    pcs_providers = pcs_summary.get("by_provider", {})
    if pcs_enabled > 0 and pcs_providers and set(pcs_providers) <= {"noop"}:
        notes.append("per-channel STT включён, но provider=noop — задать реальный provider (elevenlabs_batch)")

    return {
        "total": total,
        "would_prompt_count": would_prompt_count,
        "actual_prompt_count": actual_prompt_count,
        "would_prompt_rate": _round(would_prompt_rate),
        "actual_prompt_rate": _round(actual_prompt_rate),
        "by_decision_reason": dict(by_reason),
        "by_error_kind": dict(by_error),
        "by_situation_type": dict(by_situation),
        "top_novelty_keys": top_novelty,
        "score": score_summary,
        "latency_ms": latency_summary,
        "threshold_candidates": _threshold_candidates(scored),
        "speaker_context": speaker_summary,
        "source_reconciliation": reconcile_summary,
        "audio_capture": audio_capture_summary,
        "audio_multichannel": audio_multichannel_summary,
        "audio_per_channel_stt": pcs_summary,
        "notes": notes,
    }


def _source_reconciliation_summary(events: list[dict]) -> dict:
    """Агрегаты source reconciliation по trace-событиям (только из агрегатных полей trace)."""
    cand = [float(e["source_reconcile_candidate_count"]) for e in events
            if isinstance(e.get("source_reconcile_candidate_count"), (int, float))]
    matches = [float(e["source_reconcile_match_count"]) for e in events
               if isinstance(e.get("source_reconcile_match_count"), (int, float))]
    amb = [float(e["source_reconcile_ambiguous_count"]) for e in events
           if isinstance(e.get("source_reconcile_ambiguous_count"), (int, float))]
    rej = [float(e["source_reconcile_rejected_count"]) for e in events
           if isinstance(e.get("source_reconcile_rejected_count"), (int, float))]
    scores = [float(e["source_reconcile_average_match_score"]) for e in events
              if isinstance(e.get("source_reconcile_average_match_score"), (int, float))]
    attempt_events = [e for e in events
                      if isinstance(e.get("source_reconcile_match_attempt_count"), (int, float))]
    match_rate: Optional[float] = None
    if attempt_events:
        tot_att = sum(e["source_reconcile_match_attempt_count"] for e in attempt_events)
        tot_match = sum(e.get("source_reconcile_match_count") or 0 for e in attempt_events)
        match_rate = round(tot_match / tot_att, 4) if tot_att else None
    by_cand: Counter = Counter()
    by_reason_rc: Counter = Counter()
    for e in events:
        for field, sink in (("source_reconcile_candidate_sources", by_cand),
                            ("source_reconcile_match_reasons", by_reason_rc)):
            d = e.get(field)
            if isinstance(d, dict):
                for k, v in d.items():
                    try:
                        sink[str(k)] += int(v)
                    except (TypeError, ValueError):
                        continue
    return {
        "candidate_count_p50": _round(percentile(cand, 50), 2),
        "match_count_p50": _round(percentile(matches, 50), 2),
        "match_rate": match_rate,
        "ambiguous_count_p50": _round(percentile(amb, 50), 2),
        "rejected_count_p50": _round(percentile(rej, 50), 2),
        "average_match_score_p50": _round(percentile(scores, 50)),
        "by_candidate_source": dict(by_cand),
        "by_match_reason": dict(by_reason_rc),
    }


def _audio_per_channel_stt_summary(events: list[dict]) -> dict:
    """Агрегаты per-channel STT canary по trace-событиям (Этап 17). Только безопасные счётчики."""
    enabled_events = [e for e in events if e.get("audio_per_channel_stt_enabled")]

    def _p50(field):
        vals = [float(e[field]) for e in events if isinstance(e.get(field), (int, float))]
        return _round(percentile(vals, 50), 2)

    by_provider: Counter = Counter()
    for e in enabled_events:
        p = e.get("audio_per_channel_stt_provider")
        if p:
            by_provider[str(p)] += 1
    return {
        "events_enabled": len(enabled_events),
        "segment_finalized_p50": _p50("audio_per_channel_stt_segment_finalized_count"),
        "transcribe_success_p50": _p50("audio_per_channel_stt_transcribe_success_count"),
        "candidate_emit_p50": _p50("audio_per_channel_stt_candidate_emit_count"),
        "shadow_suppressed_p50": _p50("audio_per_channel_stt_candidate_shadow_suppressed_count"),
        "average_dominance_p50": _p50("audio_per_channel_stt_average_dominance"),
        "by_provider": dict(by_provider),
        "adapter_unavailable_p50": _p50("audio_per_channel_stt_adapter_unavailable_count"),
        "timeout_p50": _p50("audio_per_channel_stt_timeout_count"),
        "budget_exhausted_p50": _p50("audio_per_channel_stt_budget_exhausted_count"),
    }


def _audio_multichannel_summary(events: list[dict]) -> dict:
    """Агрегаты multichannel v2 shadow по trace-событиям (Этап 16). Только безопасные счётчики."""
    with_mc = [e for e in events if isinstance(e.get("audio_multichannel_frame_count"), (int, float))
               and (e.get("audio_multichannel_frame_count") or 0) > 0]

    def _p50(field):
        vals = [float(e[field]) for e in with_mc if isinstance(e.get(field), (int, float))]
        return _round(percentile(vals, 50), 2)

    return {
        "events_with_multichannel": len(with_mc),
        "frame_count_p50": _p50("audio_multichannel_frame_count"),
        "max_channels_seen_p50": _p50("audio_multichannel_max_channels_seen"),
        "parse_error_count_p50": _p50("audio_multichannel_parse_error_count"),
        "sequence_gap_count_p50": _p50("audio_multichannel_sequence_gap_count"),
        "clipping_event_count_p50": _p50("audio_multichannel_clipping_event_count"),
    }


def _audio_capture_summary(events: list[dict]) -> dict:
    """Агрегаты audio capture route по trace-событиям (Этап 15). Только техническая зона записи."""
    with_capture = [e for e in events if e.get("audio_capture_route") not in (None, "")]
    by_route: Counter = Counter()
    by_pipeline: Counter = Counter()
    by_source_kind: Counter = Counter()
    for e in with_capture:
        by_route[str(e.get("audio_capture_route"))] += 1
        if e.get("audio_capture_pipeline") not in (None, ""):
            by_pipeline[str(e.get("audio_capture_pipeline"))] += 1
        if e.get("audio_capture_source_kind") not in (None, ""):
            by_source_kind[str(e.get("audio_capture_source_kind"))] += 1
    ch = [float(e["audio_capture_actual_channel_count"]) for e in events
          if isinstance(e.get("audio_capture_actual_channel_count"), (int, float))]
    sr = [float(e["audio_capture_actual_sample_rate"]) for e in events
          if isinstance(e.get("audio_capture_actual_sample_rate"), (int, float))]
    return {
        "events_with_audio_capture": len(with_capture),
        "by_route": dict(by_route),
        "by_pipeline": dict(by_pipeline),
        "by_source_kind": dict(by_source_kind),
        "actual_channel_count_p50": _round(percentile(ch, 50), 2),
        "actual_sample_rate_p50": _round(percentile(sr, 50), 2),
    }


def _speaker_context_summary(events: list[dict]) -> dict:
    """Агрегаты speaker graph по trace-событиям (только из агрегатных полей trace)."""
    with_ctx = [e for e in events if (e.get("speaker_context_chars") or 0) > 0]
    confs = [float(e["speaker_average_confidence"]) for e in events
             if isinstance(e.get("speaker_average_confidence"), (int, float))]

    # доля событий, где есть unknown speaker side
    side_events = [e for e in events if isinstance(e.get("speaker_side_counts"), dict)]
    unknown_rate: Optional[float] = None
    if side_events:
        unk = sum(1 for e in side_events if (e["speaker_side_counts"].get("unknown") or 0) > 0)
        unknown_rate = round(unk / len(side_events), 4)

    by_source: Counter = Counter()
    for e in events:
        src = e.get("speaker_sources")
        if isinstance(src, dict):
            for k, v in src.items():
                try:
                    by_source[str(k)] += int(v)
                except (TypeError, ValueError):
                    continue

    counts = [float(e["speaker_count"]) for e in events
              if isinstance(e.get("speaker_count"), (int, float))]
    unk_counts = [float(e["speaker_unknown_side_count"]) for e in events
                  if isinstance(e.get("speaker_unknown_side_count"), (int, float))]
    hint_events = [e for e in events
                   if isinstance(e.get("speaker_hint_source_count"), (int, float))]
    hint_counts = [float(e["speaker_hint_source_count"]) for e in hint_events]
    hint_rate: Optional[float] = None
    if hint_events:
        with_hint = sum(1 for e in hint_events if e["speaker_hint_source_count"] > 0)
        hint_rate = round(with_hint / len(hint_events), 4)

    audio_counts = [float(e["speaker_audio_linked_count"]) for e in events
                    if isinstance(e.get("speaker_audio_linked_count"), (int, float))]
    channel_counts = [float(e["speaker_channel_linked_count"]) for e in events
                      if isinstance(e.get("speaker_channel_linked_count"), (int, float))]
    audio_confs = [float(e["speaker_audio_link_average_confidence"]) for e in events
                   if isinstance(e.get("speaker_audio_link_average_confidence"), (int, float))]
    audio_link_events = [e for e in events
                         if isinstance(e.get("speaker_audio_linked_count"), (int, float))]
    audio_linked_rate: Optional[float] = None
    if audio_link_events:
        with_link = sum(1 for e in audio_link_events if e["speaker_audio_linked_count"] > 0)
        audio_linked_rate = round(with_link / len(audio_link_events), 4)
    by_audio_link_source: Counter = Counter()
    for e in events:
        src = e.get("speaker_audio_link_sources")
        if isinstance(src, dict):
            for k, v in src.items():
                try:
                    by_audio_link_source[str(k)] += int(v)
                except (TypeError, ValueError):
                    continue

    # --- Этап 7: live attribution ---
    obs_counts = [float(e["speaker_audio_attribution_observation_count"]) for e in events
                  if isinstance(e.get("speaker_audio_attribution_observation_count"), (int, float))]
    link_counts = [float(e["speaker_audio_attribution_stable_link_count"]) for e in events
                   if isinstance(e.get("speaker_audio_attribution_stable_link_count"), (int, float))]
    amb_counts = [float(e["speaker_audio_attribution_ambiguous_count"]) for e in events
                  if isinstance(e.get("speaker_audio_attribution_ambiguous_count"), (int, float))]
    attr_confs = [float(e["speaker_audio_attribution_average_confidence"]) for e in events
                  if isinstance(e.get("speaker_audio_attribution_average_confidence"), (int, float))]
    attr_events = [e for e in events
                   if isinstance(e.get("speaker_audio_attribution_observation_count"), (int, float))]
    attr_rate: Optional[float] = None
    if attr_events:
        with_obs = sum(1 for e in attr_events if e["speaker_audio_attribution_observation_count"] > 0)
        attr_rate = round(with_obs / len(attr_events), 4)
    by_attr_source: Counter = Counter()
    for e in events:
        src = e.get("speaker_audio_attribution_sources")
        if isinstance(src, dict):
            for k, v in src.items():
                try:
                    by_attr_source[str(k)] += int(v)
                except (TypeError, ValueError):
                    continue

    return {
        "events_with_speaker_context": len(with_ctx),
        "avg_speaker_confidence_p50": _round(percentile(confs, 50)),
        "unknown_side_event_rate": unknown_rate,
        "by_source": dict(by_source),
        "speaker_count_p50": _round(percentile(counts, 50), 2),
        "unknown_side_count_p50": _round(percentile(unk_counts, 50), 2),
        "hint_source_count_p50": _round(percentile(hint_counts, 50), 2),
        "hint_source_event_rate": hint_rate,
        "audio_linked_event_rate": audio_linked_rate,
        "audio_linked_count_p50": _round(percentile(audio_counts, 50), 2),
        "channel_linked_count_p50": _round(percentile(channel_counts, 50), 2),
        "audio_link_confidence_p50": _round(percentile(audio_confs, 50)),
        "by_audio_link_source": dict(by_audio_link_source),
        "attribution_observation_count_p50": _round(percentile(obs_counts, 50), 2),
        "attribution_stable_link_count_p50": _round(percentile(link_counts, 50), 2),
        "attribution_ambiguous_count_p50": _round(percentile(amb_counts, 50), 2),
        "attribution_average_confidence_p50": _round(percentile(attr_confs, 50)),
        "attribution_source_event_rate": attr_rate,
        "by_attribution_source": dict(by_attr_source),
    }


def _main(argv: list[str]) -> int:
    # На Windows консоль может быть в cp1251/charmap → принудительно UTF-8 для вывода.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if len(argv) < 2:
        print("usage: python -m app.core.context.signal_trace_analysis <logfile>", file=sys.stderr)
        return 2
    path = argv[1]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        return 2
    events = load_trace_events_from_lines(lines)
    summary = analyze_signal_traces(events)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
