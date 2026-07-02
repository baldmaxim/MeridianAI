"""Multichannel shadow ingest (Этап 16): безопасные агрегаты, без raw audio."""

import array

from app.core.context.audio_frame_v2 import build_audio_frame_v2
from app.core.context.multichannel_shadow_state import AudioMultichannelShadowIngest


def _frame(seq=1, channels=2, samples=None, **kw):
    if samples is None:
        samples = (1000, -1000, 2000, -2000)
    h = dict(protocol_version=2, sequence=seq, sample_rate=16000, channels=channels, codec="pcm16",
             layout="interleaved", route="usb_recorder", capture_pipeline="multichannel_shadow_stream",
             frame_duration_ms=100, source_is_isolated=False)
    h.update(kw)
    return build_audio_frame_v2(h, array.array("h", samples).tobytes())


def test_ingest_valid_updates_counters():
    ing = AudioMultichannelShadowIngest()
    assert ing.ingest_frame(_frame(seq=1)) is True
    assert ing.ingest_frame(_frame(seq=2)) is True
    st = ing.get_stats(enabled=True)
    assert st.frame_count == 2
    assert st.last_channels == 2
    assert st.last_sample_rate == 16000
    assert st.max_channels_seen == 2
    assert st.route_counts == {"usb_recorder": 2}
    assert st.pipeline_counts == {"multichannel_shadow_stream": 2}
    assert st.enabled is True


def test_sequence_gap_counted():
    ing = AudioMultichannelShadowIngest()
    ing.ingest_frame(_frame(seq=1))
    ing.ingest_frame(_frame(seq=5))  # пропущены 2,3,4 → gap 3
    assert ing.get_stats().sequence_gap_count == 3


def test_parse_error_counted():
    ing = AudioMultichannelShadowIngest()
    assert ing.ingest_frame(b"not-a-frame") is False
    assert ing.ingest_frame(_frame(seq=1, protocol_version=1)) is False  # bad version
    st = ing.get_stats()
    assert st.parse_error_count == 2
    assert st.frame_count == 0


def test_max_channels_seen():
    ing = AudioMultichannelShadowIngest()
    ing.ingest_frame(_frame(seq=1, channels=2))
    ing.ingest_frame(_frame(seq=2, channels=4, samples=(0,) * 8))
    assert ing.get_stats().max_channels_seen == 4


def test_clipping_event_count():
    ing = AudioMultichannelShadowIngest()
    ing.ingest_frame(_frame(seq=1, samples=(32700, 0, 32700, 0)))  # ch0 clips
    ing.ingest_frame(_frame(seq=2, samples=(100, 100, 100, 100)))  # no clip
    assert ing.get_stats().clipping_event_count == 1


def test_note_dropped():
    ing = AudioMultichannelShadowIngest()
    ing.note_dropped()
    ing.note_dropped()
    assert ing.get_stats().dropped_frame_count == 2


def test_rms_p50_and_peak_max_by_channel():
    ing = AudioMultichannelShadowIngest()
    for s in [(1000, -500, 1000, -500), (2000, -500, 2000, -500), (3000, -500, 3000, -500)]:
        ing.ingest_frame(_frame(samples=s))
    st = ing.get_stats()
    assert st.rms_p50_by_channel is not None and len(st.rms_p50_by_channel) == 2
    assert st.peak_max_by_channel is not None
    assert st.peak_max_by_channel[0] >= st.rms_p50_by_channel[0]


def test_raw_payload_not_retained():
    ing = AudioMultichannelShadowIngest()
    ing.ingest_frame(_frame(samples=(12345, -9999, 4242, -4242)))
    # инстанс хранит только агрегаты — никаких bytes/payload атрибутов
    blob = repr(vars(ing))
    assert "12345" not in blob
    for v in vars(ing).values():
        assert not isinstance(v, (bytes, bytearray))


def test_clear_resets():
    ing = AudioMultichannelShadowIngest()
    ing.ingest_frame(_frame())
    ing.note_dropped()
    ing.clear()
    st = ing.get_stats()
    assert st.frame_count == 0 and st.dropped_frame_count == 0
    assert st.max_channels_seen == 0 and st.last_sequence is None
