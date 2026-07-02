"""Live speaker→audio attribution tracker (Этап 7)."""

import json
from types import SimpleNamespace

from app.core.context.speaker_audio_attribution import (
    SpeakerAudioAttributionTracker,
    SpeakerAudioObservation,
    extract_speaker_audio_observations_from_payload,
)


def _obs(label, source=None, channel=None, conf=0.0, isolated=False, src="segment_metadata"):
    return SpeakerAudioObservation(
        raw_speaker_label=label, audio_source_id=source, channel_label=channel,
        attribution_confidence=conf, source_is_isolated=isolated, source=src)


def _by_label(link_map):
    return {lk.raw_speaker_label: lk for lk in link_map.links_by_stable_id.values()}


# --- extraction ---

def test_extract_dict_segment_with_source():
    obs = extract_speaker_audio_observations_from_payload(
        {"speaker_label": "SM_0", "audio_source_id": "secondary", "attribution_confidence": 0.8})
    assert len(obs) == 1
    assert obs[0].raw_speaker_label == "SM_0"
    assert obs[0].audio_source_id == "secondary"
    assert obs[0].attribution_confidence == 0.8


def test_extract_object_attributes():
    obs = extract_speaker_audio_observations_from_payload(
        SimpleNamespace(speaker="SM_1", source_id="primary", channel="left", confidence=0.7))
    assert obs[0].raw_speaker_label == "SM_1"
    assert obs[0].audio_source_id == "primary"
    assert obs[0].channel_label == "left"


def test_extract_nested_speaker_audio_links_list():
    obs = extract_speaker_audio_observations_from_payload({"speaker_audio_links": [
        {"speaker_label": "SM_0", "audio_source_id": "secondary"},
        {"speaker_label": "SM_1", "channel_label": "right"},
    ]})
    assert {o.raw_speaker_label for o in obs} == {"SM_0", "SM_1"}


def test_extract_ignores_text_only_payload():
    obs = extract_speaker_audio_observations_from_payload(
        {"recent_dialog": "SM_0: дайте скидку", "document_context": "договор", "text": "x"})
    assert obs == []


def test_extract_ignores_record_without_label():
    obs = extract_speaker_audio_observations_from_payload({"audio_source_id": "primary"})
    assert obs == []


def test_extract_does_not_infer_side():
    obs = extract_speaker_audio_observations_from_payload(
        {"speaker_label": "SM_0", "audio_source_id": "primary", "device_role": "desktop"})
    # observation хранит технические токены, но НЕ имеет поля side
    assert not hasattr(obs[0], "side")
    assert obs[0].audio_source_id == "primary"
    assert obs[0].device_role == "desktop"


# --- tracker rules ---

def test_single_low_confidence_non_isolated_primary_no_link():
    t = SpeakerAudioAttributionTracker()
    t.observe(_obs("SM_0", source="primary", conf=0.4, isolated=False))
    assert t.build_link_map().linked_speaker_count == 0


def test_two_stable_observations_same_source_create_link():
    t = SpeakerAudioAttributionTracker()
    t.observe(_obs("SM_0", source="secondary", conf=0.6))
    t.observe(_obs("SM_0", source="secondary", conf=0.6))
    m = t.build_link_map()
    assert _by_label(m)["SM_0"].audio_source_id == "secondary"


def test_single_high_confidence_isolated_creates_link():
    t = SpeakerAudioAttributionTracker()
    t.observe(_obs("SM_0", source="secondary", conf=0.9, isolated=True))
    m = t.build_link_map()
    assert _by_label(m)["SM_0"].audio_source_id == "secondary"
    assert _by_label(m)["SM_0"].confidence >= 0.85


def test_conflicting_observations_below_dominance_are_ambiguous():
    t = SpeakerAudioAttributionTracker()
    # 1 primary, 1 secondary → dominance 0.5 < 0.67 → ambiguous, no link
    t.observe(_obs("SM_0", source="primary", conf=0.6))
    t.observe(_obs("SM_0", source="secondary", conf=0.6))
    m = t.build_link_map()
    assert m.linked_speaker_count == 0
    assert t.get_stats().ambiguous_speaker_count == 1


def test_dominance_selects_stable_source():
    t = SpeakerAudioAttributionTracker()
    for _ in range(3):
        t.observe(_obs("SM_0", source="secondary", conf=0.6))
    t.observe(_obs("SM_0", source="primary", conf=0.6))  # 3/4 secondary → 0.75 >= 0.67
    assert _by_label(t.build_link_map())["SM_0"].audio_source_id == "secondary"


def test_channel_label_included_in_link():
    t = SpeakerAudioAttributionTracker()
    # isolated high-confidence (>=0.85) → Rule B создаёт link с source И channel
    t.observe(_obs("SM_0", source="secondary", channel="right", conf=0.9, isolated=True))
    lk = _by_label(t.build_link_map())["SM_0"]
    assert lk.audio_source_id == "secondary"
    assert lk.channel_label == "right"


def test_dedupe_key_duplicate_ignored():
    t = SpeakerAudioAttributionTracker()
    p = {"speaker_label": "SM_0", "audio_source_id": "secondary",
         "attribution_confidence": 0.9, "source_is_isolated": True, "segment_id": "seg-1"}
    assert t.observe(p) is True
    assert t.observe(dict(p)) is False  # тот же segment_id → не считается
    assert t.get_stats().observation_count == 1
    assert t.get_stats().dedupe_seen_count == 1


def test_without_dedupe_key_old_behavior():
    t = SpeakerAudioAttributionTracker()
    p = {"speaker_label": "SM_0", "audio_source_id": "secondary",
         "attribution_confidence": 0.6}  # нет segment_id/dedupe_key
    assert t.observe(p) is True
    assert t.observe(dict(p)) is True  # без ключа — старое поведение (оба считаются)
    assert t.get_stats().observation_count == 2


def test_dedupe_memory_bounded():
    t = SpeakerAudioAttributionTracker(max_dedupe_keys=3)
    for i in range(5):
        t.observe({"speaker_label": f"SM_{i}", "audio_source_id": "secondary",
                   "attribution_confidence": 0.9, "source_is_isolated": True,
                   "segment_id": f"seg-{i}"})
    assert len(t._seen_dedupe_keys) <= 3  # bounded


def test_stats_counts_only_no_raw_labels():
    t = SpeakerAudioAttributionTracker()
    t.observe(_obs("SM_0", source="secondary", conf=0.9, isolated=True))
    t.observe(_obs("SM_1", source="primary", conf=0.4))  # no link (single low non-isolated generic)
    stats = t.get_stats()
    assert stats.observation_count == 2
    assert stats.speaker_count_observed == 2
    assert stats.stable_link_count == 1
    payload = json.dumps(stats.model_dump(), ensure_ascii=False)
    for leak in ("SM_0", "SM_1", "secondary", "primary"):
        assert leak not in payload
