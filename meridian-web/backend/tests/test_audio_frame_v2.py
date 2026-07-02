"""Channel-aware audio frame v2 / MAUD2 (Этап 16)."""

import array
import struct

import pytest

from app.core.context.audio_frame_v2 import (
    MAGIC,
    MAX_HEADER_BYTES,
    build_audio_frame_v2,
    compute_pcm16_interleaved_stats,
    is_audio_frame_v2,
    parse_audio_frame_v2,
)


def _pcm(samples) -> bytes:
    return array.array("h", samples).tobytes()


def _header(**kw) -> dict:
    base = dict(protocol_version=2, sequence=1, sample_rate=16000, channels=2, codec="pcm16",
                layout="interleaved", route="usb_recorder", capture_pipeline="multichannel_shadow_stream",
                frame_duration_ms=100, source_is_isolated=False)
    base.update(kw)
    return base


def _frame(samples=(1000, -1000, 2000, -2000), **kw) -> bytes:
    return build_audio_frame_v2(_header(**kw), _pcm(samples))


def test_build_and_parse_roundtrip():
    f = _frame()
    p = parse_audio_frame_v2(f)
    assert p.header.channels == 2
    assert p.header.route == "usb_recorder"
    assert p.header.capture_pipeline == "multichannel_shadow_stream"
    assert p.sample_count_per_channel == 2
    assert len(p.rms_by_channel) == 2 and len(p.peak_by_channel) == 2


def test_is_audio_frame_v2():
    assert is_audio_frame_v2(_frame()) is True
    assert is_audio_frame_v2(b"\x00\x01" * 100) is False  # legacy mono PCM
    assert is_audio_frame_v2(b"") is False
    assert is_audio_frame_v2(MAGIC) is False  # too short for header length


def test_invalid_magic_rejected():
    bad = b"XXXXX" + _frame()[5:]
    with pytest.raises(ValueError):
        parse_audio_frame_v2(bad)


def test_header_too_large_rejected():
    bad = MAGIC + struct.pack(">H", MAX_HEADER_BYTES + 1) + b"{}"
    with pytest.raises(ValueError):
        parse_audio_frame_v2(bad)


def test_invalid_json_rejected():
    bad = MAGIC + struct.pack(">H", 5) + b"{bad}" + _pcm((0, 0))
    with pytest.raises(ValueError):
        parse_audio_frame_v2(bad)


def test_invalid_protocol_version_rejected():
    with pytest.raises(ValueError):
        parse_audio_frame_v2(_frame(protocol_version=1))


def test_invalid_channels_rejected():
    with pytest.raises(ValueError):
        parse_audio_frame_v2(build_audio_frame_v2(_header(channels=99), _pcm((0,) * 99)))
    with pytest.raises(ValueError):
        parse_audio_frame_v2(build_audio_frame_v2(_header(channels=0), b""))


def test_invalid_sample_rate_rejected():
    with pytest.raises(ValueError):
        parse_audio_frame_v2(_frame(sample_rate=1000))
    with pytest.raises(ValueError):
        parse_audio_frame_v2(_frame(sample_rate=200000))


def test_invalid_codec_or_layout_rejected():
    with pytest.raises(ValueError):
        parse_audio_frame_v2(_frame(codec="opus"))
    with pytest.raises(ValueError):
        parse_audio_frame_v2(_frame(layout="planar"))


def test_payload_not_divisible_rejected():
    # 2 channels → payload must be multiple of 4 bytes; 6 bytes (3 int16) not divisible
    bad = build_audio_frame_v2(_header(channels=2), _pcm((1, 2, 3)))
    with pytest.raises(ValueError):
        parse_audio_frame_v2(bad)


def test_unknown_route_and_pipeline_coerced_not_rejected():
    p = parse_audio_frame_v2(_frame(route="our_side", capture_pipeline="weird"))
    assert p.header.route == "unknown"           # route нормализуется, не несёт сторону
    assert p.header.capture_pipeline == "unknown"


def test_stats_rms_peak_clipping_per_channel():
    # ch0 имеет клиппинг (32700/32768 ~ 0.998 >= 0.98), ch1 тихий
    stats = compute_pcm16_interleaved_stats(_pcm((32700, 100, 32700, 100)), channels=2)
    assert stats["clipping"][0] is True
    assert stats["clipping"][1] is False
    assert stats["peak"][0] > stats["peak"][1]
    assert stats["rms"][0] > stats["rms"][1]


def test_repr_has_no_raw_payload():
    p = parse_audio_frame_v2(_frame(samples=(12345, -9999, 4242, -4242)))
    r = repr(p)
    assert "payload_bytes=" in r
    assert "12345" not in r  # raw sample values не утекают в repr
    assert "\\x" not in r
