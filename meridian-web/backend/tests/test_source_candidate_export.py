"""Этап 10: candidate export helpers (multi_channel_live / secondary_shadow)."""

from app.services.multi_channel_live_session import live_multi_channel_segment_to_source_candidate
from app.services.secondary_audio_shadow import secondary_shadow_segment_to_source_candidate


def test_multi_channel_segment_to_candidate():
    seg = {"segment_id": "mc-1", "track_id": "trk_2", "channel_label": "Channel 2",
           "side": "opponent", "transcript": "дайте лучше условия", "confidence": 0.82,
           "start_server_ms": 1000, "end_server_ms": 3000}
    c = live_multi_channel_segment_to_source_candidate(seg)
    assert c is not None
    assert c["audio_source_id"] == "trk_2"
    assert c["channel_label"] == "Channel 2"
    assert c["source_kind"] == "multi_channel"
    assert c["source_is_isolated"] is True
    assert c["attribution_confidence"] == 0.82
    assert "side" not in c  # side_hint НЕ переносится как сторона


def test_multi_channel_none_without_source_or_channel():
    assert live_multi_channel_segment_to_source_candidate(
        {"transcript": "x", "start_server_ms": 1, "end_server_ms": 2}) is None


def test_multi_channel_none_without_text_and_time():
    assert live_multi_channel_segment_to_source_candidate(
        {"track_id": "trk_1"}) is None


def test_secondary_shadow_candidate_when_text_present():
    c = secondary_shadow_segment_to_source_candidate(
        {"transcript": "посмотрим по цене", "connection_id": "conn_7", "confidence": 0.8,
         "start_ms": 1000, "end_ms": 2000})
    assert c is not None
    assert c["source_kind"] == "secondary_shadow"
    assert c["attribution_source"] == "secondary_shadow_segment"
    assert "side" not in c


def test_secondary_shadow_none_for_raw_audio_only():
    # raw audio chunk без text/source → None
    assert secondary_shadow_segment_to_source_candidate(
        {"connection_id": "conn_7", "rms": 0.4, "peak": 0.9}) is None
