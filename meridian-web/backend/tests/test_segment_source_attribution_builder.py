"""Этап 9: build_segment_source_attribution_dict + attach helpers."""

import json
from dataclasses import dataclass
from typing import Optional

from app.core.context.segment_source_attribution import (
    attach_source_attribution_to_committed_segment,
    build_segment_source_attribution_dict,
    extract_segment_source_attribution,
    should_emit_speaker_audio_observation,
)


def test_build_returns_dict_for_isolated_secondary():
    d = build_segment_source_attribution_dict(
        speaker_label="SM_1", audio_source_id="secondary", channel_label="right",
        source_is_isolated=True, attribution_confidence=0.86,
        attribution_source="secondary_shadow_segment", source_kind="secondary_shadow")
    assert d is not None
    assert d["audio_source_id"] == "secondary"
    assert d["attribution_source"] == "secondary_shadow_segment"
    assert d["source_kind"] == "secondary_shadow"


def test_build_none_for_primary_room_mic_non_isolated():
    assert build_segment_source_attribution_dict(
        speaker_label="SM_0", audio_source_id="primary", source_kind="room_mic",
        source_is_isolated=False, attribution_confidence=0.9) is None


def test_build_none_without_speaker_label():
    assert build_segment_source_attribution_dict(
        audio_source_id="secondary", source_is_isolated=True, attribution_confidence=0.8) is None


def test_build_none_without_source_or_channel():
    assert build_segment_source_attribution_dict(
        speaker_label="SM_0", source_is_isolated=True, attribution_confidence=0.8) is None


def test_build_clamps_confidence():
    d = build_segment_source_attribution_dict(
        speaker_label="SM_0", audio_source_id="secondary", source_is_isolated=True,
        attribution_confidence=5.0)
    assert d["attribution_confidence"] == 1.0


def test_build_output_contains_no_side():
    d = build_segment_source_attribution_dict(
        speaker_label="SM_0", audio_source_id="secondary", source_is_isolated=True,
        attribution_confidence=0.8)
    assert "side" not in d
    assert "our_side" not in json.dumps(d, ensure_ascii=False)


def test_build_roundtrips_through_extract():
    d = build_segment_source_attribution_dict(
        speaker_label="SM_1", audio_source_id="secondary", source_is_isolated=True,
        attribution_confidence=0.8, attribution_source="multi_source_segment",
        source_kind="multi_channel")
    # привязываем как nested source_attribution и извлекаем обратно
    attr = extract_segment_source_attribution({"speaker_label": "SM_1", "source_attribution": d})
    assert attr.audio_source_id == "secondary"
    assert attr.source_kind == "multi_channel"
    assert should_emit_speaker_audio_observation(attr) is True


# --- attach ---

@dataclass
class _FakeSeg:
    speaker_label: Optional[str] = None
    source_attribution: Optional[dict] = None


def test_attach_to_object():
    seg = _FakeSeg(speaker_label="SM_0")
    attach_source_attribution_to_committed_segment(seg, {"audio_source_id": "secondary"})
    assert seg.source_attribution == {"audio_source_id": "secondary"}


def test_attach_to_dict():
    seg = {"speaker_label": "SM_0"}
    attach_source_attribution_to_committed_segment(seg, {"audio_source_id": "secondary"})
    assert seg["source_attribution"] == {"audio_source_id": "secondary"}


def test_attach_noop_when_none():
    seg = _FakeSeg(speaker_label="SM_0")
    attach_source_attribution_to_committed_segment(seg, None)
    assert seg.source_attribution is None
