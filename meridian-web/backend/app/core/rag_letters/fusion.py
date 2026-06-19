"""Чистые функции гибридного поиска: RRF-слияние и диверсификация по письму.

Без IO/БД/сети — целиком покрыто unit-тестами (tests/test_rag_letters.py).
"""

from __future__ import annotations

from typing import Callable, Iterable

# Константа RRF (Reciprocal Rank Fusion). 60 — общепринятое значение.
RRF_K = 60


def rrf_merge(ranked_lists: Iterable[list], k_const: int = RRF_K) -> dict:
    """RRF-слияние нескольких ранжированных списков id.

    ``ranked_lists`` — итерируемое из списков id (chunk_id), каждый отсортирован по убыванию
    релевантности (позиция 0 — лучший кандидат). Возвращает ``{id: fused_score}``.
    Формула: ``fused[id] += 1 / (k_const + rank)``, где ``rank`` = позиция 1..N (1 — лучший).
    Один и тот же id, встретившийся в нескольких списках, накапливает вклад каждого.
    """
    fused: dict = {}
    for lst in ranked_lists:
        for idx, cid in enumerate(lst):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k_const + idx + 1)
    return fused


def diversify(
    hits: list,
    per_letter: int = 2,
    letter_key: Callable = lambda h: getattr(h, "letter_id", None),
) -> list:
    """Оставить не более ``per_letter`` элементов на одно письмо (``letter_id``).

    Входной список ожидается уже отсортированным по убыванию релевантности — порядок
    сохраняется. Элементы с ``letter_id is None`` считаются уникальными (не группируются).
    """
    seen: dict = {}
    out: list = []
    for h in hits:
        key = letter_key(h)
        if key is not None:
            n = seen.get(key, 0)
            if n >= per_letter:
                continue
            seen[key] = n + 1
        out.append(h)
    return out
