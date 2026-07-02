"""Offline-анализатор логов SOURCE_RECONCILE_TRACE (Этап 11) — без pandas/внешних зависимостей.

Считает агрегаты для калибровки порогов reconcile перед включением active canary. Не меняет
runtime. Trace не содержит raw text/source ids/labels — анализатор работает с категориями/score.

CLI:
    python -m app.core.context.source_reconcile_trace_analysis path/to/logfile.log
"""

import json
import math
import sys
from collections import Counter
from typing import Iterable, Optional

_MARKER = "SOURCE_RECONCILE_TRACE"
_TARGET_RATES = (0.02, 0.05, 0.10)


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


def extract_source_reconcile_json_from_line(line: str) -> Optional[dict]:
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


def load_source_reconcile_events_from_lines(lines: Iterable[str]) -> list[dict]:
    out: list[dict] = []
    for line in lines:
        obj = extract_source_reconcile_json_from_line(line)
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


def _pctls(values, ps) -> dict:
    return {f"p{p}": _round(percentile(values, p)) for p in ps}


def _by(events, field) -> dict:
    c: Counter = Counter()
    for e in events:
        v = e.get(field)
        if v is not None:
            c[str(v)] += 1
    return dict(c)


def _threshold_candidates(scores: list[float]) -> list[dict]:
    out: list[dict] = []
    n = len(scores)
    for r in _TARGET_RATES:
        if n == 0:
            out.append({"target_rate": r, "score_cutoff": None, "estimated_attach_rate": 0.0,
                        "comment": "нет matched/would_attach событий"})
            continue
        cutoff = percentile(scores, (1.0 - r) * 100.0)
        kept = sum(1 for s in scores if s >= cutoff)
        out.append({"target_rate": r, "score_cutoff": _round(cutoff),
                    "estimated_attach_rate": _round(kept / n),
                    "comment": f"match_score>={_round(cutoff)} -> ~{round(kept / n * 100, 1)}% attach (по {n})"})
    return out


def analyze_source_reconcile_traces(events: list[dict]) -> dict:
    total = len(events)
    if total == 0:
        return {
            "total": 0, "would_attach_count": 0, "actual_attach_count": 0,
            "would_attach_rate": 0.0, "actual_attach_rate": 0.0,
            "by_decision_reason": {}, "by_match_reason": {}, "by_candidate_source": {},
            "by_source_kind": {}, "by_attribution_source": {},
            "score": {}, "time_overlap": {}, "text_similarity": {}, "attribution_confidence": {},
            "threshold_candidates": _threshold_candidates([]),
            "notes": ["нет SOURCE_RECONCILE_TRACE events"],
        }

    would = sum(1 for e in events if e.get("would_attach_without_shadow"))
    actual = sum(1 for e in events if e.get("actual_attach"))
    by_decision = _by(events, "decision_reason")
    by_match = _by(events, "match_reason")

    def _nums(field):
        return [float(e[field]) for e in events if isinstance(e.get(field), (int, float))]

    matched_scores = [float(e["match_score"]) for e in events
                      if e.get("would_attach_without_shadow") and isinstance(e.get("match_score"), (int, float))]

    notes: list[str] = []
    would_rate = would / total
    if by_decision.get("shadow_mode", 0) > 0 and actual == 0:
        notes.append("shadow работает, для live attach нужен source_reconcile_shadow_mode=false")
    if by_match.get("no_candidates", 0) / total > 0.5:
        notes.append("много no_candidates — нет source candidates (multi_channel_live/secondary)")
    if by_match.get("low_text_similarity", 0) / total > 0.2:
        notes.append("low_text_similarity > 20% — проверить качество/расхождение transcripts")
    if by_match.get("low_overlap", 0) / total > 0.2:
        notes.append("low_overlap > 20% — проверить шкалы timestamps")
    if by_decision.get("ambiguous", 0) > 0 or by_match.get("ambiguous", 0) > 0:
        notes.append("есть ambiguous matches — снизить overlap window или улучшить timestamps")
    if would_rate > 0.2:
        notes.append("слишком частые attach candidates (would_attach_rate > 20%) — проверить thresholds")
    score_p50 = percentile(matched_scores, 50)
    if score_p50 is not None and score_p50 < 0.65:
        notes.append("низкий match_score p50 — не расширять rollout без проверки")

    return {
        "total": total,
        "would_attach_count": would,
        "actual_attach_count": actual,
        "would_attach_rate": _round(would_rate),
        "actual_attach_rate": _round(actual / total),
        "by_decision_reason": by_decision,
        "by_match_reason": by_match,
        "by_candidate_source": _by(events, "candidate_source"),
        "by_source_kind": _by(events, "source_kind"),
        "by_attribution_source": _by(events, "attribution_source"),
        "score": _pctls(_nums("match_score"), (50, 75, 90, 95)),
        "time_overlap": _pctls(_nums("time_overlap"), (50, 90, 95)),
        "text_similarity": _pctls(_nums("text_similarity"), (50, 90, 95)),
        "attribution_confidence": _pctls(_nums("attribution_confidence"), (50, 90, 95)),
        "threshold_candidates": _threshold_candidates(matched_scores),
        "notes": notes,
    }


def _main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if len(argv) < 2:
        print("usage: python -m app.core.context.source_reconcile_trace_analysis <logfile>", file=sys.stderr)
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
    summary = analyze_source_reconcile_traces(load_source_reconcile_events_from_lines(lines))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
