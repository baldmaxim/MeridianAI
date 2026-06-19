"""Тесты сравнения batch-кандидата с live transcript (Этап 9.5) — чистые функции."""

from types import SimpleNamespace

from app.services.multi_channel_transcript_compare import (
    compare_batch_with_live,
    normalize_transcript_text,
    tokenize_transcript,
    word_error_rate,
)


def ch(idx, transcript, conf=None):
    return SimpleNamespace(channel_index=idx, transcript=transcript, average_confidence=conf)


def seg(idx, start, end, text=""):
    return SimpleNamespace(channel_index=idx, start=start, end=end,
                           segment_id=f"s{idx}-{start}", text=text)


def result(channels, chrono):
    return SimpleNamespace(channels=list(channels), chronological_segments=tuple(chrono))


# --- normalize / tokenize ---

def test_normalize_case_punct_yo():
    assert normalize_transcript_text("Привёт, МИР!!!") == "привет мир"
    assert normalize_transcript_text("ёлка — Ель") == "елка ель"


def test_normalize_keeps_digits():
    assert normalize_transcript_text("дом 12, кв. 3") == "дом 12 кв 3"


def test_tokenize_empty():
    assert tokenize_transcript("   ") == []
    assert tokenize_transcript("раз два") == ["раз", "два"]


# --- WER ---

def test_wer_identical():
    assert word_error_rate(["привет", "мир"], ["привет", "мир"]) == 0.0


def test_wer_both_empty():
    assert word_error_rate([], []) == 0.0


def test_wer_empty_reference_is_none():
    assert word_error_rate([], ["привет"]) is None


def test_wer_substitution():
    assert word_error_rate(["привет", "мир"], ["привет", "дом"]) == 0.5


def test_wer_full_deletion():
    # пустой hypothesis при непустом reference → все слова удалены → WER 1.0
    assert word_error_rate(["а", "б", "в"], []) == 1.0


def test_wer_bounded_max_words():
    ref = ["x"] * 100000
    hyp = ["x"] * 100000
    # max_words ограничивает CPU/память (две строки) — должно вернуться без зависания
    assert word_error_rate(ref, hyp, max_words=500) == 0.0


# --- compare_batch_with_live ---

def test_compare_identical():
    live = [{"text": "Привет, мир!"}]
    r = result([ch(0, "привет мир", 0.9)], [seg(0, 0.0, 1.0, "привет мир")])
    out = compare_batch_with_live(batch_result=r, live_segments=live)
    assert out["available"] is True
    assert out["word_error_rate"] == 0.0
    assert out["text_similarity"] == 1.0
    assert out["channels_with_text"] == 1
    assert out["empty_channels"] == []


def test_compare_empty_live():
    r = result([ch(0, "привет", 0.9)], [seg(0, 0, 1, "привет")])
    out = compare_batch_with_live(batch_result=r, live_segments=[])
    assert out["available"] is False
    assert out["word_error_rate"] is None
    assert out["batch_words"] == 1


def test_compare_uses_chronological_order_for_dialog():
    # диалог: live = a b c d (хронологически), batch-каналы = (a c)|(b d).
    # WER должен считаться по хронологическому порядку → 0, а не по поканальной склейке.
    live = [{"text": "a"}, {"text": "b"}, {"text": "c"}, {"text": "d"}]
    chrono = [seg(0, 0.0, 0.5, "a"), seg(1, 0.5, 1.0, "b"),
              seg(0, 1.0, 1.5, "c"), seg(1, 1.5, 2.0, "d")]
    r = result([ch(0, "a c", 0.9), ch(1, "b d", 0.9)], chrono)
    out = compare_batch_with_live(batch_result=r, live_segments=live)
    assert out["word_error_rate"] == 0.0
    assert out["batch_words"] == 4


def test_compare_empty_batch():
    live = [{"text": "привет мир"}]
    r = result([ch(0, "", None)], [])
    out = compare_batch_with_live(batch_result=r, live_segments=live)
    assert out["available"] is True
    assert out["word_error_rate"] == 1.0          # всё удалено
    assert out["channels_with_text"] == 0
    assert out["empty_channels"] == [0]


def test_compare_confidence_average():
    r = result([ch(0, "a", 0.8), ch(1, "b", 0.6)], [seg(0, 0, 1), seg(1, 0, 1)])
    out = compare_batch_with_live(batch_result=r, live_segments=[{"text": "a b"}])
    assert out["average_confidence"] == 0.7


def test_compare_overlap_detected():
    # ch0 [0,2], ch1 [1,3] → перекрытие 1с между РАЗНЫМИ каналами
    r = result([ch(0, "x", 0.9), ch(1, "y", 0.9)], [seg(0, 0.0, 2.0), seg(1, 1.0, 3.0)])
    out = compare_batch_with_live(batch_result=r, live_segments=[{"text": "x y"}])
    assert out["overlap_segments"] == 1
    assert out["overlap_duration_ms"] == 1000


def test_compare_no_overlap_same_channel_ignored():
    # один канал, последовательные — не пересечение; и пересечений между каналами нет
    r = result([ch(0, "x y", 0.9)], [seg(0, 0.0, 1.0), seg(0, 2.0, 3.0)])
    out = compare_batch_with_live(batch_result=r, live_segments=[{"text": "x y"}])
    assert out["overlap_segments"] == 0
    assert out["overlap_duration_ms"] == 0
