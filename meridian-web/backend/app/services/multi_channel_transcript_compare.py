"""Сравнение batch-кандидата с live transcript (Этап 9.5) — чистые функции.

Live transcript НЕ эталон и НЕ мутируется — сравнение только диагностическое.
"""

import re

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)


def normalize_transcript_text(text: str) -> str:
    """lowercase, ё→е, без пунктуации, схлопнутые пробелы. Цифры сохраняем, без стемминга."""
    t = (text or "").lower().replace("ё", "е")
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def tokenize_transcript(text: str) -> list[str]:
    n = normalize_transcript_text(text)
    return n.split(" ") if n else []


def word_error_rate(reference: list[str], hypothesis: list[str], *,
                    max_words: int = 5000) -> float | None:
    """WER (Levenshtein по токенам), bounded по памяти (две строки) и по длине (max_words).

    Оба пустые → 0.0. Пустой reference при непустом hypothesis → None (WER не определён).
    """
    ref = reference[:max_words]
    hyp = hypothesis[:max_words]
    if not ref and not hyp:
        return 0.0
    if not ref:
        return None  # нет эталонных слов — WER не определён
    prev = list(range(len(hyp) + 1))
    for r in ref:
        cur = [prev[0] + 1]
        for j, h in enumerate(hyp, 1):
            cost = 0 if r == h else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[len(hyp)] / len(ref)


def _seg_text(s) -> str:
    if isinstance(s, dict):
        return str(s.get("text") or "")
    return str(getattr(s, "text", "") or "")


def _overlap_stats(segments: list) -> tuple[int, int]:
    """Пары segments РАЗНЫХ каналов с пересечением по времени: (count, суммарные мс).

    Sweep по start (O(n·активные)), не полный O(n²). segments имеют .start/.end (сек),
    .channel_index. Пересекающиеся реплики НЕ объединяются и НЕ удаляются.
    """
    segs = sorted(segments, key=lambda s: (s.start, s.end))
    active: list[tuple] = []  # (end, channel_index)
    count = 0
    total_ms = 0.0
    for s in segs:
        active = [a for a in active if a[0] > s.start]
        for (a_end, a_ch) in active:
            if a_ch != s.channel_index:
                ov = min(a_end, s.end) - s.start
                if ov > 0:
                    count += 1
                    total_ms += ov * 1000.0
        active.append((s.end, s.channel_index))
    return count, int(round(total_ms))


def compare_batch_with_live(*, batch_result, live_segments: list) -> dict:
    """Сравнить batch-кандидат с live committed-сегментами (read-only).

    live_segments — список объектов/словарей с полем text. Если live пуст →
    available=false (job всё равно succeeded).
    """
    live_items = live_segments or []
    live_texts = [_seg_text(s) for s in live_items]
    live_text = " ".join(t for t in live_texts if t)
    live_tokens = tokenize_transcript(live_text)

    # batch-текст в ХРОНОЛОГИЧЕСКОМ порядке (как live committed_segments), а не
    # поканально — иначе для диалога МЫ/НЕ МЫ WER/similarity завышены искусственно.
    batch_text = " ".join(s.text for s in batch_result.chronological_segments if s.text)
    batch_tokens = tokenize_transcript(batch_text)

    available = bool(live_tokens)
    wer = word_error_rate(live_tokens, batch_tokens) if available else None
    similarity = (max(0.0, min(1.0, 1.0 - wer)) if wer is not None else None)

    channels_with_text = sum(1 for ch in batch_result.channels if ch.transcript.strip())
    empty_channels = [ch.channel_index for ch in batch_result.channels if not ch.transcript.strip()]
    confs = [ch.average_confidence for ch in batch_result.channels
             if ch.average_confidence is not None]
    avg_conf = round(sum(confs) / len(confs), 4) if confs else None
    ov_count, ov_ms = _overlap_stats(list(batch_result.chronological_segments))

    return {
        "available": available,
        "live_words": len(live_tokens),
        "batch_words": len(batch_tokens),
        "live_chars": len(live_text),
        "batch_chars": len(batch_text),
        "word_error_rate": round(wer, 4) if wer is not None else None,
        "text_similarity": round(similarity, 4) if similarity is not None else None,
        "channels_with_text": channels_with_text,
        "empty_channels": empty_channels,
        "average_confidence": avg_conf,
        "overlap_segments": ov_count,
        "overlap_duration_ms": ov_ms,
        "warnings": [],
    }
