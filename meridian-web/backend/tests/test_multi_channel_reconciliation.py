"""Тесты channel-aware reconciliation (Этап 9.7) — scoring + matching + side agreement."""

from app.services.multi_channel_reconciliation import (
    ChannelTranscriptSegmentView, PrimaryTranscriptSegmentView,
    generate_candidate_pairs, normalize_reconciliation_text, reconcile_segments,
    reconciliation_pair_score, side_hint_confidence, temporal_overlap_score,
    text_similarity_score,
)

MATCH = 0.68
SUGGEST = 0.78
MINPAIR = 0.45
AMB = 0.08
DELTA = 2000


def pv(key, text, start, end, *, side=None, has_corr=False, corr_side=None, corrected_label=None,
       orig="DG_S0", eff="DG_S0"):
    return PrimaryTranscriptSegmentView(
        segment_key=key, text=text, start_server_ms=start, end_server_ms=end,
        original_speaker_label=orig, effective_speaker_label=eff, current_side=side,
        has_segment_correction=has_corr, correction_side=corr_side, corrected_speaker_label=corrected_label)


def cv(sid, ci, text, start, end, *, side="opponent", conf=0.9):
    return ChannelTranscriptSegmentView(
        segment_id=sid, session_id="sess", channel_index=ci, channels_count=2,
        track_id=f"t{ci}", source_connection_id=f"c{ci}", source_kind="secondary",
        generation=0, channel_label=f"Канал {ci}", channel_side=side, text=text,
        start_server_ms=start, end_server_ms=end, provider_confidence=conf, speech_final=True)


def run(primary, channel, **over):
    kw = dict(meeting_id=1, session_id="sess", primary_segments=primary, channel_segments=channel,
              max_time_delta_ms=DELTA, min_pair_score=MINPAIR, match_score=MATCH,
              suggest_score=SUGGEST, ambiguity_delta=AMB, max_entries=300, revision=1)
    kw.update(over)
    return reconcile_segments(**kw)


# ============================ scoring ============================

def test_normalize_and_similarity():
    assert normalize_reconciliation_text("Привёт, МИР!") == "привет мир"
    assert text_similarity_score("привет мир", "Привет, мир!") > 0.9
    assert text_similarity_score("", "x") == 0.0
    assert text_similarity_score("a b", "") == 0.0


def test_temporal_exact_and_partial():
    full = temporal_overlap_score(left_start_ms=1000, left_end_ms=2000,
                                  right_start_ms=1000, right_end_ms=2000, max_time_delta_ms=DELTA)
    part = temporal_overlap_score(left_start_ms=1000, left_end_ms=2000,
                                  right_start_ms=1500, right_end_ms=2500, max_time_delta_ms=DELTA)
    assert full > part > 0


def test_temporal_close_no_overlap_and_beyond():
    close = temporal_overlap_score(left_start_ms=1000, left_end_ms=2000,
                                   right_start_ms=2500, right_end_ms=3000, max_time_delta_ms=DELTA)
    beyond = temporal_overlap_score(left_start_ms=1000, left_end_ms=2000,
                                    right_start_ms=9000, right_end_ms=9500, max_time_delta_ms=DELTA)
    assert 0 < close < 0.5 and beyond == 0.0


def test_temporal_exact_coincidence_is_one():
    # точное совпадение (в т.ч. нулевая длительность) → 1.0, а не gap-ветка 0.5
    assert temporal_overlap_score(left_start_ms=500, left_end_ms=500,
                                  right_start_ms=500, right_end_ms=500, max_time_delta_ms=DELTA) == 1.0
    assert temporal_overlap_score(left_start_ms=1000, left_end_ms=2000,
                                  right_start_ms=1000, right_end_ms=2000, max_time_delta_ms=DELTA) == 1.0


def test_generate_pairs_excludes_far_past_candidate():
    # длинный кандидат рядом + короткий далеко-в-прошлом; нижняя граница окна должна отсечь далёкий
    primary = [pv("p0", "встреча сегодня", 100000, 101000)]
    channel = [cv("near", 1, "встреча сегодня", 100000, 101000),
               cv("farpast", 0, "встреча сегодня", 1000, 1500)]
    pairs = generate_candidate_pairs(primary_segments=primary, channel_segments=channel,
                                     max_time_delta_ms=DELTA, min_pair_score=0.0)  # порог 0 → видны все
    cids = {channel[p[1]].segment_id for p in pairs}
    assert "near" in cids and "farpast" not in cids


def test_temporal_invalid_and_bool():
    assert temporal_overlap_score(left_start_ms=2000, left_end_ms=1000,
                                  right_start_ms=1000, right_end_ms=2000, max_time_delta_ms=DELTA) == 0.0
    assert temporal_overlap_score(left_start_ms=True, left_end_ms=2000,
                                  right_start_ms=1000, right_end_ms=2000, max_time_delta_ms=DELTA) == 0.0


def test_pair_score_clamped():
    temporal, text, total = reconciliation_pair_score(
        primary=pv("p", "привет мир", 1000, 2000), candidate=cv("c", 1, "привет мир", 1000, 2000),
        max_time_delta_ms=DELTA)
    assert 0.0 <= total <= 1.0 and total > MATCH


def test_hint_confidence_penalties():
    # baseline с good clock (None/poor штрафуются по спеку)
    base = side_hint_confidence(match_score=0.9, provider_confidence=0.9, clock_quality="good")
    poor = side_hint_confidence(match_score=0.9, provider_confidence=0.9, clock_quality="poor")
    unknown = side_hint_confidence(match_score=0.9, provider_confidence=0.9, clock_quality=None)
    silent = side_hint_confidence(match_score=0.9, provider_confidence=0.9,
                                  clock_quality="good", channel_silence_ratio=0.9)
    assert poor < base and silent < base and unknown < base
    assert 0.0 <= poor <= 1.0


# ============================ pair generation ============================

def test_generate_pairs_windowed_and_deterministic():
    primary = [pv("p0", "раз два", 1000, 2000), pv("p1", "далеко", 100000, 101000)]
    channel = [cv("c0", 1, "раз два", 1000, 2000), cv("c1", 0, "около", 500000, 501000)]
    pairs = generate_candidate_pairs(primary_segments=primary, channel_segments=channel,
                                     max_time_delta_ms=DELTA, min_pair_score=MINPAIR)
    # p1/c1 далеко по времени — не должны попасть; p0/c0 близко
    assert any(p[0] == 0 and p[1] == 0 for p in pairs)
    assert all(not (p[0] == 1 and p[1] == 1) for p in pairs)
    assert pairs == sorted(pairs, key=lambda x: (x[0], x[1]))


# ============================ matching ============================

def test_simple_one_to_one_matched_suggested():
    p = [pv("p0", "привет мир", 1000, 2000, side=None)]
    c = [cv("c0", 1, "привет мир", 1000, 2000, side="opponent")]
    st = run(p, c)
    e = st.entries[0]
    assert e.kind == "matched" and e.side_agreement == "suggested"
    assert e.can_apply_side is True
    assert e.entry_id == "reconcile:p0:c0"
    assert st.summary.matched == 1 and st.summary.suggested == 1


def test_same_side_confirmed_not_applicable():
    p = [pv("p0", "привет мир", 1000, 2000, side="opponent")]
    c = [cv("c0", 1, "привет мир", 1000, 2000, side="opponent")]
    st = run(p, c)
    e = st.entries[0]
    assert e.side_agreement == "confirmed" and e.can_apply_side is False


def test_conflict_requires_confirmation():
    p = [pv("p0", "привет мир", 1000, 2000, side="self")]
    c = [cv("c0", 1, "привет мир", 1000, 2000, side="opponent")]
    st = run(p, c)
    e = st.entries[0]
    assert e.side_agreement == "conflict" and e.requires_conflict_confirmation is True
    assert e.can_apply_side is True       # применимо, но требует подтверждения


def test_unknown_channel_side():
    p = [pv("p0", "привет мир", 1000, 2000, side=None)]
    c = [cv("c0", 1, "привет мир", 1000, 2000, side=None)]
    st = run(p, c)
    e = st.entries[0]
    assert e.side_agreement == "unknown" and e.can_apply_side is False


def test_existing_correction_requires_confirmation():
    p = [pv("p0", "привет мир", 1000, 2000, side=None, has_corr=True)]
    c = [cv("c0", 1, "привет мир", 1000, 2000, side="opponent")]
    e = run(p, c).entries[0]
    assert e.requires_conflict_confirmation is True


def test_ambiguous_one_primary_two_close_candidates():
    p = [pv("p0", "привет мир", 1000, 2000, side=None)]
    c = [cv("cA", 0, "привет мир", 1000, 2000, side="self"),
         cv("cB", 1, "привет мир", 1050, 2050, side="opponent")]
    st = run(p, c)
    amb = [e for e in st.entries if e.kind == "ambiguous"]
    assert len(amb) == 1 and amb[0].can_apply_side is False
    assert len(amb[0].alternatives) >= 2


def test_two_primary_one_candidate():
    p = [pv("p0", "привет мир", 1000, 2000, side=None),
         pv("p1", "привет мир", 1000, 2000, side=None)]
    c = [cv("c0", 1, "привет мир", 1000, 2000, side="opponent")]
    st = run(p, c)
    kinds = sorted(e.kind for e in st.entries)
    assert "matched" in kinds and "primary_only" in kinds
    # один channel не matched дважды
    assert sum(1 for e in st.entries if e.kind == "matched") == 1


def test_channel_only_and_primary_only():
    p = [pv("p0", "встреча сегодня", 1000, 2000, side=None)]
    c = [cv("c0", 1, "совершенно другое", 100000, 101000, side="opponent")]
    st = run(p, c)
    kinds = {e.kind for e in st.entries}
    assert "channel_only" in kinds and "primary_only" in kinds
    assert st.summary.channel_only == 1 and st.summary.primary_only == 1


def test_overlapping_channels_not_collapsed():
    p = [pv("p0", "мы говорим", 1000, 3000, side=None)]
    c = [cv("cA", 0, "мы говорим", 1000, 2000, side="self"),
         cv("cB", 1, "они говорят", 1500, 3000, side="opponent")]
    st = run(p, c)
    # оба channel сегмента учтены (не объединены): как alternatives ambiguous либо channel_only
    seen = set()
    for e in st.entries:
        if e.channel_segment_id:
            seen.add(e.channel_segment_id)
        for a in e.alternatives:
            seen.add(a.channel_segment_id)
    assert {"cA", "cB"} <= seen


def test_low_score_not_matched():
    p = [pv("p0", "абсолютно уникальный текст", 1000, 2000, side=None)]
    c = [cv("c0", 1, "ничего общего вообще", 1900, 2900, side="opponent")]
    st = run(p, c)
    assert all(e.kind != "matched" for e in st.entries)


def test_max_entries_truncation_priority():
    # много primary_only + один conflict → conflict в приоритете при truncation до 1
    p = [pv(f"p{i}", f"реплика номер {i}", 1000 + i * 5000, 2000 + i * 5000, side=None)
         for i in range(5)]
    p.append(pv("pc", "конфликт реплика", 1000, 2000, side="self"))
    c = [cv("cc", 1, "конфликт реплика", 1000, 2000, side="opponent")]
    st = run(p, c, max_entries=1)
    assert st.truncated is True
    assert st.entries[0].side_agreement == "conflict"
    # summary считает ВСЕ обработанные, не только показанные
    assert st.summary.primary_only == 5
