"""Этап 7: MeetingRoom._speaker_audio_attribution_payload (helper-level, без websocket/audio)."""

from types import SimpleNamespace

from app.services.meeting_room import MeetingRoom

# Метод не использует self → зовём как unbound с self=None (без тяжёлой конструкции комнаты).
_payload = MeetingRoom._speaker_audio_attribution_payload


def test_payload_none_when_no_per_speaker_source():
    # обычный CommittedSegment-подобный объект: есть label, но нет source/channel → no-op
    seg = SimpleNamespace(speaker_label="SM_0")
    assert _payload(None, seg) is None


def test_payload_none_without_label():
    seg = SimpleNamespace(audio_source_id="secondary")
    assert _payload(None, seg) is None


def test_payload_built_with_isolated_source():
    seg = SimpleNamespace(speaker_label="SM_0", audio_source_id="secondary",
                          channel_label="right", attribution_confidence=0.82,
                          source_is_isolated=True, segment_id="seg-9")
    p = _payload(None, seg)
    assert p is not None
    assert p["speaker_label"] == "SM_0"
    assert p["audio_source_id"] == "secondary"
    assert p["channel_label"] == "right"
    assert p["source_is_isolated"] is True
    assert p["segment_id"] == "seg-9"  # dedupe key


def test_payload_none_for_primary_room_mic_non_isolated():
    seg = SimpleNamespace(speaker_label="SM_0", audio_source_id="primary",
                          source_kind="room_mic", source_is_isolated=False,
                          attribution_confidence=0.9)
    assert _payload(None, seg) is None


def test_source_only_candidate_does_not_become_speaker_observation():
    # Этап 10: per-channel кандидат БЕЗ speaker_label → идёт в reconciler (observe_source_candidate),
    # НЕ в observe_speaker_audio_attribution (build_observation_payload_from_segment вернёт None).
    from app.core.context.segment_source_attribution import build_observation_payload_from_segment
    from app.services.multi_channel_live_session import live_multi_channel_segment_to_source_candidate
    seg = {"segment_id": "mc-1", "track_id": "trk_2", "channel_label": "Channel 2",
           "transcript": "дайте лучше условия", "start_server_ms": 1000, "end_server_ms": 3000}
    assert live_multi_channel_segment_to_source_candidate(seg) is not None  # candidate ok
    assert build_observation_payload_from_segment(seg) is None  # НЕ speaker observation (нет label)


def test_payload_from_nested_source_attribution():
    seg = SimpleNamespace(speaker_label="SM_1", segment_id="seg-1", source_attribution={
        "audio_source_id": "secondary", "channel_label": "right", "source_is_isolated": True,
        "attribution_confidence": 0.86, "attribution_source": "secondary_shadow_segment",
        "source_kind": "secondary_shadow"})
    p = _payload(None, seg)
    assert p is not None
    assert p["source"] == "secondary_shadow"
    assert p["segment_id"] == "seg-1"
