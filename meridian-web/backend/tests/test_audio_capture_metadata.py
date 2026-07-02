"""Safe audio capture route metadata (Этап 15)."""

import json

from app.core.context.audio_capture_metadata import (
    AudioCaptureMetadata,
    hash_audio_token,
    normalize_audio_capture_route,
    normalize_capture_pipeline,
    parse_audio_capture_metadata,
    sanitize_browser_name,
)


def test_normalize_route_and_pipeline():
    assert normalize_audio_capture_route("usb_recorder") == "usb_recorder"
    assert normalize_audio_capture_route("hacker") == "unknown"
    assert normalize_audio_capture_route(None) == "unknown"
    assert normalize_capture_pipeline("mono_stream") == "mono_stream"
    assert normalize_capture_pipeline("weird") == "unknown"


def test_hash_audio_token():
    h = hash_audio_token("Zoom H2n USB Audio")
    assert isinstance(h, str) and len(h) == 16
    assert h == hash_audio_token("Zoom H2n USB Audio")  # стабильный
    assert hash_audio_token("Zoom H2n USB Audio") != "Zoom H2n USB Audio"
    assert hash_audio_token(None) is None
    assert hash_audio_token("  ") is None


def test_sanitize_browser_name():
    assert sanitize_browser_name("Chrome") == "Chrome"
    long_ua = "Mozilla/5.0 " + "x" * 300
    assert len(sanitize_browser_name(long_ua)) == 80  # обрезано, не полный UA
    assert sanitize_browser_name(None) is None
    assert sanitize_browser_name("a\nb") == "a b"


def test_parse_raw_label_and_id_hashed_not_stored():
    m = parse_audio_capture_metadata({
        "route": "usb_recorder", "deviceLabel": "Zoom H2n USB Audio",
        "deviceId": "raw-hardware-id-1234567890",
    })
    blob = json.dumps(m.model_dump(), ensure_ascii=False)
    assert "Zoom H2n" not in blob
    assert "raw-hardware-id" not in blob
    assert m.device_label_hash and m.device_label_hash == hash_audio_token("Zoom H2n USB Audio")
    assert m.device_id_hash and m.device_id_hash == hash_audio_token("raw-hardware-id-1234567890")


def test_parse_existing_hashes_passthrough():
    m = parse_audio_capture_metadata({"route": "laptop_mic", "deviceLabelHash": "abc123def456",
                                      "deviceIdHash": "0011223344556677"})
    assert m.device_label_hash == "abc123def456"
    assert m.device_id_hash == "0011223344556677"


def test_invalid_route_becomes_unknown():
    assert parse_audio_capture_metadata({"route": "our_side"}).route == "unknown"
    assert parse_audio_capture_metadata({"route": "counterparty"}).route == "unknown"


def test_channel_sample_clamp_and_sanitize():
    m = parse_audio_capture_metadata({
        "route": "usb_recorder", "actualChannelCount": 999, "requestedChannelCount": -3,
        "actualSampleRate": 9999999, "requestedSampleRate": 100,
    })
    assert m.actual_channel_count == 32       # clamp hi
    assert m.requested_channel_count == 1     # clamp lo
    assert m.actual_sample_rate == 768000     # clamp hi
    assert m.requested_sample_rate == 4000    # clamp lo


def test_bad_numeric_values_become_none():
    m = parse_audio_capture_metadata({"route": "laptop_mic", "actualChannelCount": "two",
                                      "actualSampleRate": None})
    assert m.actual_channel_count is None
    assert m.actual_sample_rate is None


def test_source_is_isolated_default_false():
    assert parse_audio_capture_metadata({"route": "usb_recorder"}).source_is_isolated is False
    assert parse_audio_capture_metadata({}).source_is_isolated is False


def test_route_does_not_imply_side():
    # ни одно поле модели не несёт speaker_side; source_kind — техническая категория записи
    m = parse_audio_capture_metadata({"route": "usb_recorder"})
    d = m.model_dump()
    assert "side" not in d
    assert "speaker_side" not in d
    assert d["source_kind"] in ("room_mic", "usb_recorder", "speakerphone", "secondary_device", "unknown")


def test_source_kind_derived_from_route():
    assert parse_audio_capture_metadata({"route": "usb_room_mic"}).source_kind == "room_mic"
    assert parse_audio_capture_metadata({"route": "speakerphone_usb"}).source_kind == "speakerphone"
    assert parse_audio_capture_metadata({"route": "phone_secondary"}).source_kind == "secondary_device"
    assert parse_audio_capture_metadata({"route": "laptop_mic"}).source_kind == "unknown"
    # явный source_kind имеет приоритет (нормализованный)
    assert parse_audio_capture_metadata({"route": "usb_recorder", "sourceKind": "room_mic"}).source_kind == "room_mic"
    assert parse_audio_capture_metadata({"route": "usb_recorder", "sourceKind": "evil"}).source_kind == "unknown"


def test_parse_object_and_garbage():
    class _Obj:
        route = "speakerphone_usb"
        actualChannelCount = 1
    assert parse_audio_capture_metadata(_Obj()).route == "speakerphone_usb"
    assert parse_audio_capture_metadata(None) == AudioCaptureMetadata()
    assert parse_audio_capture_metadata(42).route == "unknown"
    assert parse_audio_capture_metadata("string").route == "unknown"


def test_bool_coercion():
    m = parse_audio_capture_metadata({"route": "laptop_mic", "echoCancellation": "true",
                                      "noiseSuppression": False, "autoGainControl": 1})
    assert m.echo_cancellation is True
    assert m.noise_suppression is False
    assert m.auto_gain_control is True
