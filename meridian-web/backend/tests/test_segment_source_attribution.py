"""Committed segment source attribution (Этап 8)."""

import json
from types import SimpleNamespace

from app.core.context.segment_source_attribution import (
    extract_segment_source_attribution,
    segment_source_attribution_to_observation_payload,
    should_emit_speaker_audio_observation,
)


def _safe(**kw):
    base = dict(audio_source_id="secondary", source_is_isolated=True,
                attribution_confidence=0.86, attribution_source="secondary_shadow_segment",
                source_kind="secondary_shadow")
    base.update(kw)
    return base


# --- extract ---

def test_extract_flat_dict():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_1", "audio_source_id": "secondary", "channel_label": "right",
         "attribution_confidence": 0.8, "source_is_isolated": True})
    assert a.speaker_label == "SM_1"
    assert a.audio_source_id == "secondary"
    assert a.channel_label == "right"
    assert a.source_is_isolated is True


def test_extract_nested_source_attribution():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_1", "text": "договор", "source_attribution": _safe()})
    assert a.audio_source_id == "secondary"
    assert a.attribution_source == "secondary_shadow_segment"
    assert a.source_kind == "secondary_shadow"


def test_extract_object_attributes():
    a = extract_segment_source_attribution(
        SimpleNamespace(speaker="SM_2", source_id="primary", channel="left", confidence=0.7))
    assert a.speaker_label == "SM_2"
    assert a.audio_source_id == "primary"
    assert a.channel_label == "left"


def test_extract_none_without_label():
    assert extract_segment_source_attribution({"audio_source_id": "secondary"}) is None
    assert extract_segment_source_attribution(None) is None


def test_extract_ignores_text_fields():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_0", "text": "дайте скидку", "recent_dialog": "x", "transcript": "y"})
    # есть label, но нет source/channel → attr без source; текст не извлекается
    assert a.audio_source_id is None
    assert a.channel_label is None


def test_extract_never_has_side():
    a = extract_segment_source_attribution({"speaker_label": "SM_0", "audio_source_id": "secondary"})
    assert not hasattr(a, "side")


# --- should_emit ---

def test_should_emit_false_primary_room_mic_non_isolated():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_0", "audio_source_id": "primary",
         "source_kind": "room_mic", "source_is_isolated": False, "attribution_confidence": 0.9})
    assert should_emit_speaker_audio_observation(a) is False


def test_should_emit_false_desktop_phone_non_isolated():
    for tok in ("desktop", "phone"):
        a = extract_segment_source_attribution(
            {"speaker_label": "SM_0", "audio_source_id": tok, "attribution_confidence": 0.9})
        assert should_emit_speaker_audio_observation(a) is False


def test_should_emit_true_isolated_secondary():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_0", "audio_source_id": "secondary",
         "source_is_isolated": True, "attribution_confidence": 0.6})
    assert should_emit_speaker_audio_observation(a) is True


def test_should_emit_true_multi_channel_kind():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_0", "channel_label": "ch2",
         "source_kind": "multi_channel", "attribution_confidence": 0.6})
    assert should_emit_speaker_audio_observation(a) is True


def test_should_emit_false_generic_token_nonisolated_even_if_multi_channel():
    # Этап 10 safety-review: generic-токен primary + source_kind=multi_channel + isolated=False → блок
    for kind in ("multi_channel", "isolated_source", "secondary_shadow"):
        a = extract_segment_source_attribution(
            {"speaker_label": "SM_0", "audio_source_id": "primary", "source_kind": kind,
             "source_is_isolated": False, "attribution_confidence": 0.9})
        assert should_emit_speaker_audio_observation(a) is False


def test_should_emit_false_low_confidence():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_0", "audio_source_id": "secondary",
         "source_is_isolated": True, "attribution_confidence": 0.4})
    assert should_emit_speaker_audio_observation(a) is False


# --- payload ---

def test_payload_maps_attribution_source():
    cases = {
        "multi_source_segment": "multi_source_ingest",
        "secondary_shadow_segment": "secondary_shadow",
        "diarization_result": "diarization_metadata",
        "manual_runtime_metadata": "manual_runtime_metadata",
    }
    for attr_src, obs_src in cases.items():
        a = extract_segment_source_attribution(
            {"speaker_label": "SM_0", "audio_source_id": "secondary",
             "source_is_isolated": True, "attribution_confidence": 0.8,
             "attribution_source": attr_src})
        p = segment_source_attribution_to_observation_payload(a)
        assert p["source"] == obs_src


def test_payload_contains_no_side():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_0", "audio_source_id": "secondary",
         "source_is_isolated": True, "attribution_confidence": 0.8})
    p = segment_source_attribution_to_observation_payload(a)
    assert "side" not in p
    assert json.dumps(p, ensure_ascii=False).find("our_side") == -1


def test_payload_none_when_should_not_emit():
    a = extract_segment_source_attribution(
        {"speaker_label": "SM_0", "audio_source_id": "primary", "source_kind": "room_mic"})
    assert segment_source_attribution_to_observation_payload(a) is None
