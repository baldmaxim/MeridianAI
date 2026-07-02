"""Speaker ↔ audio/channel links (Этап 6): нормализация и извлечение из metadata."""

from types import SimpleNamespace

from app.core.context.speaker_audio_links import (
    build_speaker_audio_link_map,
    extract_audio_links_from_metadata,
    is_generic_room_source_token,
    make_speaker_audio_link,
    normalize_audio_token,
)


def test_is_generic_room_source_token():
    for t in ("primary", "desktop", "phone", "default", "room", "mono", "laptop",
              "microphone", "mic", "browser", "unknown", "PRIMARY", " Desktop "):
        assert is_generic_room_source_token(t) is True
    for t in ("secondary", "track_7", "left", "right", "isolated_mic_2", None, ""):
        assert is_generic_room_source_token(t) is False


def _by_label(m):
    return {lk.raw_speaker_label: lk for lk in m.links_by_stable_id.values()}


def test_normalize_audio_token_strips_newlines_and_caps_length():
    assert normalize_audio_token("  primary \n source ") == "primary source"
    assert normalize_audio_token("x" * 200) == "x" * 80
    assert normalize_audio_token("") is None
    assert normalize_audio_token(None) is None


def test_make_speaker_audio_link_builds_stable_id():
    a = make_speaker_audio_link("SM_0", audio_source_id="primary", source="audio_source_metadata")
    b = make_speaker_audio_link("SM_0", channel_label="left", source="channel_metadata")
    assert a.stable_id == b.stable_id  # одинаковый label → один stable_id
    assert a.audio_source_id == "primary"
    assert a.source == "audio_source_metadata"


def test_build_map_counts_and_avg():
    links = [
        make_speaker_audio_link("SM_0", audio_source_id="primary", confidence=0.8, source="audio_source_metadata"),
        make_speaker_audio_link("SM_1", channel_label="left", confidence=0.6, source="channel_metadata"),
    ]
    m = build_speaker_audio_link_map(links)
    assert m.linked_speaker_count == 2
    assert m.audio_source_count == 1
    assert m.channel_label_count == 1
    assert 0.0 < m.average_confidence <= 1.0
    assert m.source_summary == {"audio_source_metadata": 1, "channel_metadata": 1}


def test_extract_dict_label_to_source():
    m = extract_audio_links_from_metadata(audio_source_metadata={"SM_0": "primary", "SM_1": "secondary"})
    byl = _by_label(m)
    assert byl["SM_0"].audio_source_id == "primary"
    assert byl["SM_1"].audio_source_id == "secondary"
    assert m.linked_speaker_count == 2


def test_extract_dict_label_to_object():
    m = extract_audio_links_from_metadata(audio_source_metadata={
        "SM_0": {"audio_source_id": "primary", "channel_label": "left", "confidence": 0.8},
        "SM_1": {"source_id": "secondary", "channel": "right"},
    })
    byl = _by_label(m)
    assert byl["SM_0"].audio_source_id == "primary"
    assert byl["SM_0"].channel_label == "left"
    assert byl["SM_1"].audio_source_id == "secondary"
    assert byl["SM_1"].channel_label == "right"


def test_extract_known_containers():
    m = extract_audio_links_from_metadata(audio_source_metadata={
        "speaker_sources": {"SM_0": "primary"},
        "speaker_channels": {"SM_0": "left"},
    })
    byl = _by_label(m)
    assert byl["SM_0"].audio_source_id == "primary"
    assert byl["SM_0"].channel_label == "left"  # merged source+channel for SM_0


def test_extract_list_of_dicts_and_objects():
    m = extract_audio_links_from_metadata(audio_source_metadata=[
        {"speaker_label": "SM_0", "audio_source_id": "primary", "channel_label": "left"},
        SimpleNamespace(speaker="SM_1", source="secondary", channel="right"),
    ])
    byl = _by_label(m)
    assert byl["SM_0"].audio_source_id == "primary"
    assert byl["SM_1"].audio_source_id == "secondary"
    assert byl["SM_1"].channel_label == "right"


def test_extract_ignores_records_without_label():
    m = extract_audio_links_from_metadata(audio_source_metadata=[
        {"audio_source_id": "primary"},  # нет label
        {"speaker_label": "SM_0", "audio_source_id": "primary"},
    ])
    assert m.linked_speaker_count == 1


def test_extract_does_not_infer_side():
    # значения primary/desktop/phone не становятся стороной — это только id, не side
    m = extract_audio_links_from_metadata(audio_source_metadata={"SM_0": "desktop"})
    lk = _by_label(m)["SM_0"]
    assert lk.audio_source_id == "desktop"
    # в SpeakerAudioLink вообще нет поля side — связь не несёт стороны
    assert not hasattr(lk, "side")


def test_extract_empty_returns_empty_map():
    m = extract_audio_links_from_metadata()
    assert m.links_by_stable_id == {}
    assert m.linked_speaker_count == 0
