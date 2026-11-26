"""Пословные таймкоды сегментов встречи для подсветки слов в плеере.

Чистые функции без БД: разбор words_json живых встреч и раздача слов батча по сегментам.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from typing import Any, Iterable, Sequence

BATCH_WORDS_EPS = 0.05


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_words(items: Iterable[Any]) -> list[dict]:
    """Оставить только слова: {text, start, end}; spacing/punctuation и мусор отбросить."""
    result: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind is not None and kind != "word":
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        start, end = item.get("start"), item.get("end")
        if not _is_number(start) or not _is_number(end):
            continue
        result.append({"text": text.strip(), "start": float(start), "end": float(end)})
    return result


def parse_words_json(raw: str | None) -> list[dict] | None:
    """words_json сегмента -> список слов; битый JSON, не список или пусто -> None."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    return clean_words(data) or None


def assign_batch_words(
    segments: Sequence[tuple[float, float]],
    words: Iterable[Any],
    eps: float = BATCH_WORDS_EPS,
) -> list[list[dict] | None]:
    """Раздать слова батча по сегментам (start, end) по времени.

    Слово попадает в сегмент, если seg.start - eps <= word.start <= seg.end + eps; каждое слово
    используется один раз (первым по времени подходящим сегментом). Результат — по индексам входа,
    None — слов нет.
    """
    ordered = sorted(clean_words(words), key=lambda w: w["start"])
    starts = [w["start"] for w in ordered]
    used = [False] * len(ordered)
    result: list[list[dict] | None] = [None] * len(segments)

    for idx in sorted(range(len(segments)), key=lambda i: segments[i][0]):
        seg_start, seg_end = segments[idx]
        picked: list[dict] = []
        pos = bisect_left(starts, seg_start - eps)
        while pos < len(ordered) and starts[pos] <= seg_end + eps:
            if not used[pos]:
                used[pos] = True
                picked.append(ordered[pos])
            pos += 1
        result[idx] = picked or None
    return result
