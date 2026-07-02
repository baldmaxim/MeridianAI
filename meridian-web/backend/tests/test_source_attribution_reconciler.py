"""Source Attribution Reconciliation v1 (Этап 10)."""

import json

from app.core.context.source_attribution_reconciler import (
    SourceAttributionReconciler,
    extract_source_candidate_from_payload,
    normalize_reconcile_text,
    text_similarity,
    time_overlap_ratio,
)


def _cand(**kw):
    base = dict(text="дайте лучше условия и скидку", start_ms=1000, end_ms=3000,
                audio_source_id="secondary", source_is_isolated=True, source_kind="multi_channel",
                attribution_source="multi_source_segment", attribution_confidence=0.8,
                candidate_pipeline="multi_channel_live")
    base.update(kw)
    return base


def _seg(**kw):
    base = dict(speaker_label="SM_1", segment_id="s1", text="дайте лучше условия и скидку",
                start_ms=1100, end_ms=2900)
    base.update(kw)
    return base


# --- helpers ---

def test_normalize_and_text_similarity():
    assert normalize_reconcile_text("Привет, МИР!!!") == "привет мир"
    assert text_similarity("Привет, мир!", "привет мир") > 0.95
    assert text_similarity("abc", "xyz") < 0.5
    assert text_similarity("", "x") == 0.0


def test_time_overlap_ratio():
    assert time_overlap_ratio(1000, 3000, 1100, 2900) == 1.0  # contained
    assert time_overlap_ratio(1000, 2000, 1500, 2500) == 0.5
    assert time_overlap_ratio(1000, 2000, 3000, 4000) == 0.0
    assert time_overlap_ratio(None, 2000, 1, 2) == 0.0


# --- observe ---

def test_observe_candidate_valid():
    r = SourceAttributionReconciler()
    assert r.observe_candidate(_cand()) is True
    assert r.get_stats().candidate_count == 1


def test_reject_candidate_without_source_or_channel():
    r = SourceAttributionReconciler()
    assert r.observe_candidate({"text": "x", "start_ms": 1, "end_ms": 2}) is False


def test_reject_room_mic_non_isolated_primary():
    r = SourceAttributionReconciler()
    assert r.observe_candidate(_cand(audio_source_id="primary", source_kind="room_mic",
                                     source_is_isolated=False)) is False


def test_accept_isolated_multi_channel():
    r = SourceAttributionReconciler()
    assert r.observe_candidate(_cand(source_kind="multi_channel", source_is_isolated=True)) is True


def test_reject_generic_token_nonisolated_even_if_multi_channel():
    # safety-review: generic primary token + source_kind=multi_channel + isolated=False → reject
    r = SourceAttributionReconciler()
    assert r.observe_candidate(_cand(audio_source_id="primary", source_kind="multi_channel",
                                     source_is_isolated=False)) is False
    assert r.observe_candidate(_cand(audio_source_id="desktop", source_kind="isolated_source",
                                     source_is_isolated=False)) is False


def test_reject_low_candidate_confidence():
    r = SourceAttributionReconciler()
    assert r.observe_candidate(_cand(attribution_confidence=0.4)) is False


# --- reconcile ---

def test_reconcile_time_plus_text_match():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand())
    m = r.reconcile_segment(_seg())
    assert m.matched is True
    assert m.reason == "matched"
    assert m.attribution_dict["speaker_label"] == "SM_1"        # из committed segment
    assert m.attribution_dict["audio_source_id"] == "secondary"  # из candidate
    assert "side" not in m.attribution_dict


def test_reconcile_explicit_turn_index():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand(text=None, start_ms=None, end_ms=None, turn_index=5))
    m = r.reconcile_segment(_seg(text=None, start_ms=None, end_ms=None, turn_index=5))
    assert m.matched is True


def test_reconcile_reject_low_text_similarity():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand(text="совершенно другой текст про погоду"))
    m = r.reconcile_segment(_seg())
    assert m.matched is False
    assert m.reason in ("low_text_similarity", "low_confidence")


def test_reconcile_reject_low_time_overlap():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand(start_ms=10000, end_ms=12000))
    m = r.reconcile_segment(_seg())
    assert m.matched is False
    assert m.reason in ("low_overlap", "low_text_similarity", "low_confidence")


def test_text_only_requires_very_high_similarity_and_unique():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand(start_ms=None, end_ms=None))  # no time, text identical
    m = r.reconcile_segment(_seg(start_ms=None, end_ms=None))
    assert m.matched is True
    # два text-only кандидата → ambiguous
    r2 = SourceAttributionReconciler()
    r2.observe_candidate(_cand(start_ms=None, end_ms=None))
    r2.observe_candidate(_cand(start_ms=None, end_ms=None, audio_source_id="channel_b"))
    m2 = r2.reconcile_segment(_seg(start_ms=None, end_ms=None))
    assert m2.matched is False and m2.reason == "ambiguous"


def test_time_only_requires_high_overlap_and_confidence():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand(text=None, attribution_confidence=0.9, start_ms=1000, end_ms=3000))
    m = r.reconcile_segment(_seg(text=None, start_ms=1050, end_ms=2950))
    assert m.matched is True
    # низкая confidence → reject
    r2 = SourceAttributionReconciler()
    r2.observe_candidate(_cand(text=None, attribution_confidence=0.6, start_ms=1000, end_ms=3000))
    m2 = r2.reconcile_segment(_seg(text=None, start_ms=1050, end_ms=2950))
    assert m2.matched is False


def test_ambiguous_top_two_within_margin():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand(audio_source_id="ch_a"))
    r.observe_candidate(_cand(audio_source_id="ch_b"))  # identical metrics → tie
    m = r.reconcile_segment(_seg())
    assert m.matched is False
    assert m.reason == "ambiguous"
    assert r.get_stats().ambiguous_count == 1


def test_reconcile_no_speaker_label():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand())
    m = r.reconcile_segment(_seg(speaker_label=None))
    assert m.matched is False and m.reason == "no_speaker_label"


def test_reconcile_already_attributed():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand())
    seg = _seg()
    seg["source_attribution"] = {"audio_source_id": "x"}
    m = r.reconcile_segment(seg)
    assert m.matched is False and m.reason == "already_attributed"


def test_attribution_dict_no_side_and_uses_committed_speaker():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand())
    m = r.reconcile_segment(_seg())
    payload = json.dumps(m.attribution_dict, ensure_ascii=False)
    assert "our_side" not in payload and "counterparty" not in payload
    assert m.attribution_dict["speaker_label"] == "SM_1"


def test_stats_counts_only_no_raw():
    r = SourceAttributionReconciler()
    r.observe_candidate(_cand())
    r.reconcile_segment(_seg())
    stats = r.get_stats()
    payload = json.dumps(stats.model_dump(), ensure_ascii=False)
    for leak in ("SM_1", "secondary", "дайте", "s1"):
        assert leak not in payload
    assert stats.match_count == 1


def test_bounded_candidate_buffer():
    r = SourceAttributionReconciler(max_candidates=3, max_age_ms=0)
    for i in range(6):
        r.observe_candidate(_cand(audio_source_id=f"ch_{i}", start_ms=1000 + i, end_ms=2000 + i))
    assert r.get_stats().candidate_count <= 3


def test_apply_runtime_config_changes_thresholds_and_prunes():
    from types import SimpleNamespace
    r = SourceAttributionReconciler()
    for i in range(5):
        r.observe_candidate(_cand(audio_source_id=f"ch_{i}", start_ms=1000 + i, end_ms=2000 + i))
    assert r.get_stats().candidate_count == 5
    cfg = SimpleNamespace(min_candidate_confidence=0.7, min_time_overlap=0.5,
                          min_text_similarity=0.9, min_match_score=0.8, ambiguity_margin=0.05,
                          max_candidates=2, max_age_ms=120000)
    r.apply_runtime_config(cfg)
    assert r.min_text_similarity == 0.9
    assert r.min_match_score == 0.8
    assert r.max_candidates == 2
    assert r.get_stats().candidate_count <= 2  # buffer обрезан


def test_extract_from_nested_container():
    c = extract_source_candidate_from_payload(
        {"text": "x", "source_attribution_candidate": {"audio_source_id": "secondary",
         "source_is_isolated": True, "source_kind": "multi_channel", "attribution_confidence": 0.8}})
    assert c is not None
    assert c.audio_source_id == "secondary"
