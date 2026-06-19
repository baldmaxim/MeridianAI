"""Сборка авторитетного транскрипта поверх эпох (Этап 9.8)."""

from app.services.authoritative_transcript import (
    EpochView, SingleSegmentView, MultiSegmentView, build_authoritative_transcript,
)


def sv(key, text, start, end, side=None, speaker=None):
    return SingleSegmentView(segment_key=key, text=text, speech_start_ms=start,
                             speech_end_ms=end, side=side, speaker=speaker)


def mv(key, text, start, end, side=None, label=None):
    return MultiSegmentView(segment_key=key, text=text, start_server_ms=start,
                            end_server_ms=end, side=side, channel_label=label)


def test_no_epochs_single_only_ordered():
    singles = [sv("a", "привет", 2000, 3000, "self"), sv("b", "как дела", 1000, 1500, "opponent")]
    t = build_authoritative_transcript(epochs=[], single_segments=singles, multi_segments=[])
    assert t.epochs_count == 0 and t.sources_used == ("single",)
    assert [s.segment_key for s in t.segments] == ["b", "a"]


def test_no_epochs_ignores_multi():
    t = build_authoritative_transcript(epochs=[], single_segments=[sv("a", "x", 0, 1)],
                                       multi_segments=[mv("m", "y", 0, 1)])
    assert [s.segment_key for s in t.segments] == ["a"]


def test_epoch_selection_excludes_single_in_multi_range():
    epochs = [EpochView(0, "single", 0, 10000), EpochView(1, "multi_channel", 10000, None)]
    singles = [sv("s1", "раз", 1000, 2000, "self"), sv("s2", "два", 9000, 9500, "opponent"),
               sv("s3", "хвост single в multi-эпохе", 10500, 11000, "self")]
    multis = [mv("m2", "три", 12000, 13000, "opponent")]
    t = build_authoritative_transcript(epochs=epochs, single_segments=singles, multi_segments=multis)
    keys = [s.segment_key for s in t.segments]
    assert "s3" not in keys                       # single в multi-эпохе исключён
    assert keys == ["s1", "s2", "m2"]
    assert t.sources_used == ("single", "multi_channel")


def test_boundary_dedupe_drops_later_duplicate():
    epochs = [EpochView(0, "single", 0, 10000), EpochView(1, "multi_channel", 10000, None)]
    singles = [sv("s1", "спасибо за встречу", 9000, 9900, "self")]
    multis = [mv("m1", "спасибо за встречу", 10100, 11000, "self"),   # дубль у границы
              mv("m2", "следующий вопрос", 12000, 13000, "opponent")]
    t = build_authoritative_transcript(epochs=epochs, single_segments=singles, multi_segments=multis,
                                       boundary_dedupe_ms=1000, boundary_dedupe_similarity=0.6)
    assert [s.segment_key for s in t.segments] == ["s1", "m2"]


def test_dedupe_disabled_keeps_both():
    epochs = [EpochView(0, "single", 0, 10000), EpochView(1, "multi_channel", 10000, None)]
    singles = [sv("s1", "спасибо за встречу", 9000, 9900, "self")]
    multis = [mv("m1", "спасибо за встречу", 10100, 11000, "self")]
    t = build_authoritative_transcript(epochs=epochs, single_segments=singles, multi_segments=multis,
                                       boundary_dedupe_ms=0)
    assert [s.segment_key for s in t.segments] == ["s1", "m1"]


def test_dedupe_keeps_distinct_text():
    epochs = [EpochView(0, "single", 0, 10000), EpochView(1, "multi_channel", 10000, None)]
    singles = [sv("s1", "первая мысль", 9000, 9900, "self")]
    multis = [mv("m1", "совсем другое", 10100, 11000, "opponent")]
    t = build_authoritative_transcript(epochs=epochs, single_segments=singles, multi_segments=multis,
                                       boundary_dedupe_ms=1000, boundary_dedupe_similarity=0.6)
    assert [s.segment_key for s in t.segments] == ["s1", "m1"]


def test_full_and_recent_text_with_side_labels():
    singles = [sv("s1", "раз", 1000, 2000, "self"), sv("s2", "два", 600000, 601000, "opponent")]
    t = build_authoritative_transcript(epochs=[], single_segments=singles, multi_segments=[])
    full = t.full_text()
    assert "раз" in full and "два" in full and "МЫ" in full and "НЕ МЫ" in full
    recent = t.recent_text(now_ms=601000, minutes=5)
    assert "два" in recent and "раз" not in recent


def test_full_text_truncation_keeps_tail():
    singles = [sv(f"s{i}", "x" * 40, i * 1000, i * 1000 + 500, "self") for i in range(30)]
    t = build_authoritative_transcript(epochs=[], single_segments=singles, multi_segments=[])
    out = t.full_text(max_chars=100)
    assert len(out) <= 100 and "s29" not in out  # хвост — последние реплики (текст, не ключи)


def test_full_text_truncation_starts_on_line_boundary():
    # после tail-обрезки первая строка не должна быть обрезана посреди «[tc] СТОРОНА:»
    singles = [sv(f"s{i}", f"реплика номер {i} " + "y" * 20, i * 1000, i * 1000 + 500, "self")
               for i in range(40)]
    t = build_authoritative_transcript(epochs=[], single_segments=singles, multi_segments=[])
    out = t.full_text(max_chars=120)
    assert len(out) <= 120
    first_line = out.split("\n", 1)[0]
    assert first_line.startswith("[")  # целый префикс таймкода, не фрагмент


def test_to_dict_shape():
    epochs = [EpochView(0, "single", 0, 10000), EpochView(1, "multi_channel", 10000, None)]
    singles = [sv("s1", "раз", 1000, 2000, "self")]
    multis = [mv("m1", "два", 11000, 12000, "opponent")]
    t = build_authoritative_transcript(epochs=epochs, single_segments=singles, multi_segments=multis)
    d = t.to_dict()
    assert d["epochs_count"] == 2 and d["segment_count"] == 2
    assert {s["source"] for s in d["segments"]} == {"single", "multi_channel"}
