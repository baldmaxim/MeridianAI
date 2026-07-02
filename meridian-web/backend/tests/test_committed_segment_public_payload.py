"""Этап 9: source_attribution не утекает в public/frontend payload committed-сегмента."""

import json

from app.core.context.segment_source_attribution import public_committed_segment_payload
from app.core.transcription.models import CommittedSegment

_TECH_KEYS = ("source_attribution", "audio_source_id", "channel_label", "device_role",
              "route", "source_is_isolated", "attribution_source", "source_kind",
              "attribution_confidence")


def _seg_with_attribution():
    seg = CommittedSegment(speaker_label="SM_1", segment_id="seg-1", text="привет")
    seg.source_attribution = {
        "audio_source_id": "secondary", "channel_label": "right", "source_is_isolated": True,
        "attribution_confidence": 0.86, "attribution_source": "secondary_shadow_segment",
        "source_kind": "secondary_shadow",
    }
    return seg


def test_to_wire_full_excludes_source_attribution():
    seg = _seg_with_attribution()
    payload = json.dumps(seg.to_wire_full(), ensure_ascii=False)
    for k in _TECH_KEYS:
        assert k not in payload
    assert "secondary" not in payload  # raw source id не утёк


def test_to_wire_excludes_source_attribution():
    seg = _seg_with_attribution()
    payload = json.dumps(seg.to_wire(), ensure_ascii=False)
    for k in _TECH_KEYS:
        assert k not in payload


def test_to_dict_persistence_excludes_source_attribution():
    seg = _seg_with_attribution()
    d = seg.to_dict()
    for k in _TECH_KEYS:
        assert k not in d


def test_public_payload_helper_strips_technical_keys():
    # даже если кто-то добавит technical-ключи в wire dict — helper их вырежет
    seg = _seg_with_attribution()
    d = public_committed_segment_payload(seg)
    for k in _TECH_KEYS:
        assert k not in d
    # обычные публичные поля остаются
    assert d["segment_id"] == "seg-1"
    assert d["text"] == "привет"


def test_public_payload_helper_on_raw_dict():
    d = public_committed_segment_payload({
        "segment_id": "x", "text": "y", "source_attribution": {"audio_source_id": "secondary"},
        "audio_source_id": "secondary"})
    assert "source_attribution" not in d
    assert "audio_source_id" not in d
    assert d["segment_id"] == "x"
