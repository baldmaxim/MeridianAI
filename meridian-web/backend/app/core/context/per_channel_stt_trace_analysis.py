"""Offline-анализатор логов PER_CHANNEL_STT_TRACE (Этап 17) — без внешних зависимостей.

Считает агрегаты per-channel STT canary для решения о включении source_reconcile active. Trace не
содержит raw text/audio/source ids — анализатор работает только со счётчиками/средними/категориями.

CLI:
    python -m app.core.context.per_channel_stt_trace_analysis path/to/logfile.log
"""

import json
import math
import sys
from collections import Counter
from typing import Iterable, Optional

_MARKER = "PER_CHANNEL_STT_TRACE"


def _first_balanced_object(text: str) -> Optional[str]:
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


def extract_per_channel_stt_json_from_line(line: str) -> Optional[dict]:
    if not line or _MARKER not in line:
        return None
    snippet = _first_balanced_object(line.split(_MARKER, 1)[1])
    if snippet is None:
        return None
    try:
        obj = json.loads(snippet)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def load_per_channel_stt_events_from_lines(lines: Iterable[str]) -> list[dict]:
    out: list[dict] = []
    for line in lines:
        obj = extract_per_channel_stt_json_from_line(line)
        if obj is not None:
            out.append(obj)
    return out


def percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return xs[int(k)]
    return xs[lo] * (hi - k) + xs[hi] * (k - lo)


def _round(v: Optional[float], n: int = 4) -> Optional[float]:
    return None if v is None else round(v, n)


def _nums(events, field):
    return [float(e[field]) for e in events if isinstance(e.get(field), (int, float))]


def _sum(events, field):
    return sum(int(e[field]) for e in events if isinstance(e.get(field), (int, float)))


def analyze_per_channel_stt_traces(events: list[dict]) -> dict:
    total = len(events)
    if total == 0:
        return {
            "total": 0, "enabled_event_count": 0, "candidate_emit_count": 0,
            "candidate_shadow_suppressed_count": 0, "transcribe_success_count": 0,
            "transcribe_error_count": 0, "segment_finalized_count": 0,
            "segment_drop_rates": {"low_rms": 0, "low_dominance": 0, "rate_limit": 0},
            "max_channels_seen_p50": None, "average_dominance_p50": None,
            "average_transcribe_latency_p95_ms": None, "by_last_error_kind": {},
            "by_provider": {}, "cache_hit_rate": None, "budget_exhausted_count": 0,
            "adapter_unavailable_count": 0, "timeout_count": 0, "provider_error_count": 0,
            "provider_calls_used": 0, "provider_audio_seconds_used": 0.0,
            "notes": ["нет событий PER_CHANNEL_STT_TRACE"],
        }

    enabled_count = sum(1 for e in events if e.get("enabled"))
    candidate_emit = _sum(events, "candidate_emit_count")
    shadow_suppressed = _sum(events, "candidate_shadow_suppressed_count")
    transcribe_success = _sum(events, "transcribe_success_count")
    transcribe_error = _sum(events, "transcribe_error_count")
    seg_finalized = _sum(events, "segment_finalized_count")
    frame_total = _sum(events, "frame_count")
    drop_low_rms = _sum(events, "segment_dropped_low_rms_count")
    drop_low_dom = _sum(events, "segment_dropped_low_dominance_count")
    drop_rate = _sum(events, "segment_dropped_rate_limit_count")
    max_ch_p50 = _round(percentile(_nums(events, "max_channels_seen"), 50), 2)
    dom_p50 = _round(percentile(_nums(events, "average_dominance"), 50))
    lat_p95 = _round(percentile(_nums(events, "average_transcribe_latency_ms"), 95), 1)

    by_err: Counter = Counter()
    for e in events:
        ek = e.get("last_error_kind")
        if ek:
            by_err[str(ek)] += 1
    by_provider: Counter = Counter()
    for e in events:
        p = e.get("provider")
        if p:
            by_provider[str(p)] += 1

    # Provider adapter aggregates (Этап 18)
    timeout_count = _sum(events, "transcribe_timeout_count")
    provider_error_count = _sum(events, "transcribe_provider_error_count")
    budget_exhausted_count = _sum(events, "transcribe_budget_exhausted_count")
    adapter_unavailable_count = _sum(events, "adapter_unavailable_count")
    empty_text_count = _sum(events, "transcribe_empty_text_count")
    cache_hit = _sum(events, "transcribe_cache_hit_count")
    cache_miss = _sum(events, "transcribe_cache_miss_count")
    cache_total = cache_hit + cache_miss
    cache_hit_rate = round(cache_hit / cache_total, 4) if cache_total else None

    # Budget/cost (Этап 20) — cumulative, берём max (последний снимок)
    def _max(field):
        vals = [float(e[field]) for e in events if isinstance(e.get(field), (int, float))]
        return max(vals) if vals else 0
    provider_calls_used = int(_max("provider_calls_used"))
    provider_audio_seconds_used = round(float(_max("provider_audio_seconds_used")), 2)

    notes: list[str] = []
    if max_ch_p50 is not None and max_ch_p50 < 2:
        notes.append("per-channel STT нужно 2+ канала — проверить Stage 16 multichannel shadow")
    if seg_finalized == 0 and frame_total > 0:
        notes.append("frames есть, но 0 finalized сегментов — VAD/dominance пороги, возможно, слишком строгие")
    if seg_finalized > 0 and drop_low_dom / max(seg_finalized + drop_low_dom, 1) > 0.5:
        notes.append("много сегментов отброшено по low_dominance — каналы не изолированы/не доминантны")
    if transcribe_error > 0 and transcribe_error >= transcribe_success:
        notes.append("STT adapter errors преобладают — проверить адаптер (возможно, stt_adapter_unavailable)")
    if shadow_suppressed > 0 and candidate_emit == 0:
        notes.append("per-channel STT в shadow подавляет кандидатов — снять per-channel shadow, чтобы "
                     "кормить source reconciler")
    if lat_p95 is not None and lat_p95 > 4000:
        notes.append("высокая latency p95 per-channel STT — учесть стоимость/задержку")
    # provider adapter notes (Этап 18)
    noop_or_unavailable = by_provider.get("noop", 0) + adapter_unavailable_count
    if transcribe_success == 0 and (noop_or_unavailable > 0 or by_provider.get("noop", 0) > 0):
        notes.append("real STT adapter not active (provider=noop / adapter unavailable)")
    if by_err.get("api_key_missing", 0) > 0:
        notes.append("provider configured but API key missing")
    if timeout_count > 0:
        notes.append("provider timeout — снизить max_audio_seconds или увеличить timeout_seconds")
    if budget_exhausted_count > 0:
        notes.append("budget exhausted — слишком строгий бюджет или слишком много сегментов")
    if empty_text_count > 0 and empty_text_count >= transcribe_success:
        notes.append("много empty_text — сегменты короткие/шумные или качество STT низкое")

    return {
        "total": total,
        "enabled_event_count": enabled_count,
        "candidate_emit_count": candidate_emit,
        "candidate_shadow_suppressed_count": shadow_suppressed,
        "transcribe_success_count": transcribe_success,
        "transcribe_error_count": transcribe_error,
        "segment_finalized_count": seg_finalized,
        "segment_drop_rates": {
            "low_rms": drop_low_rms, "low_dominance": drop_low_dom, "rate_limit": drop_rate},
        "max_channels_seen_p50": max_ch_p50,
        "average_dominance_p50": dom_p50,
        "average_transcribe_latency_p95_ms": lat_p95,
        "by_last_error_kind": dict(by_err),
        "by_provider": dict(by_provider),
        "cache_hit_rate": cache_hit_rate,
        "budget_exhausted_count": budget_exhausted_count,
        "adapter_unavailable_count": adapter_unavailable_count,
        "timeout_count": timeout_count,
        "provider_error_count": provider_error_count,
        "provider_calls_used": provider_calls_used,
        "provider_audio_seconds_used": provider_audio_seconds_used,
        "notes": notes,
    }


def _main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if len(argv) < 2:
        print("usage: python -m app.core.context.per_channel_stt_trace_analysis <logfile>", file=sys.stderr)
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
    summary = analyze_per_channel_stt_traces(load_per_channel_stt_events_from_lines(lines))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
