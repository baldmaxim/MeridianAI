"""Тесты Deepgram multichannel batch adapter + pure parser (Этап 9.5)."""

import math

import httpx
import pytest

from app.services.multi_channel_batch_stt import MultiChannelBatchSttError
from app.services.multi_channel_wav import build_pcm16_wav_header
from app.services.deepgram_multi_channel_batch import (
    DeepgramMultiChannelBatchProvider,
    parse_deepgram_multichannel_response,
)

MAPPING = [
    {"channel_index": 0, "track_id": "a", "channel_label": "Основной канал",
     "side": "self", "source_kind": "primary", "generation": 0},
    {"channel_index": 1, "track_id": "b", "channel_label": "Shadow — Не мы",
     "side": "opponent", "source_kind": "secondary", "generation": 0},
]


def dg_ok():
    return {
        "metadata": {"request_id": "req-123", "duration": 2.0, "channels": 2, "language": "ru"},
        "results": {
            "channels": [
                {"alternatives": [{"transcript": "Привет", "confidence": 0.9,
                                   "words": [{"word": "привет", "punctuated_word": "Привет",
                                              "start": 0.1, "end": 0.5, "confidence": 0.9}]}]},
                {"alternatives": [{"transcript": "да", "confidence": 0.8,
                                   "words": [{"word": "да", "start": 0.2, "end": 0.4, "confidence": 0.8}]}]},
            ],
            "utterances": [
                {"channel": 0, "start": 0.1, "end": 0.5, "transcript": "Привет", "confidence": 0.9},
                {"channel": 1, "start": 0.2, "end": 0.4, "transcript": "да", "confidence": 0.8},
            ],
        },
    }


# ============================ parser ============================

def test_parse_two_channels_mapping():
    r = parse_deepgram_multichannel_response(
        data=dg_ok(), expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert r.channels_count == 2
    assert r.channels[0].track_id == "a" and r.channels[0].side == "self"
    assert r.channels[1].track_id == "b" and r.channels[1].side == "opponent"
    assert r.channels[0].transcript == "Привет"
    assert r.provider_request_id == "req-123"
    assert r.channels[0].words_count == 1


def test_parse_chronological_and_combined():
    r = parse_deepgram_multichannel_response(
        data=dg_ok(), expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    starts = [s.start for s in r.chronological_segments]
    assert starts == sorted(starts)
    assert r.chronological_segments[0].channel_index == 0   # 0.1 < 0.2
    assert "[МЫ | Канал 1]" in r.combined_text
    assert "[НЕ МЫ | Канал 2]" in r.combined_text


def test_parse_overlaps_not_merged():
    data = dg_ok()
    # обе реплики пересекаются по времени, но это разные каналы — не объединять
    data["results"]["utterances"] = [
        {"channel": 0, "start": 0.0, "end": 2.0, "transcript": "раз"},
        {"channel": 1, "start": 1.0, "end": 3.0, "transcript": "два"},
    ]
    r = parse_deepgram_multichannel_response(
        data=data, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert len(r.chronological_segments) == 2


def test_parse_empty_channel():
    data = dg_ok()
    data["results"]["channels"][1] = {"alternatives": [{"transcript": "", "words": []}]}
    data["results"]["utterances"] = [u for u in data["results"]["utterances"] if u["channel"] != 1]
    r = parse_deepgram_multichannel_response(
        data=data, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert r.channels[1].transcript == ""
    assert r.channels[1].segments_count == 0


def test_parse_fewer_channels_warns():
    data = dg_ok()
    data["results"]["channels"] = [data["results"]["channels"][0]]
    data["results"]["utterances"] = [u for u in data["results"]["utterances"] if u["channel"] == 0]
    r = parse_deepgram_multichannel_response(
        data=data, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert r.channels[1].transcript == ""
    assert any("меньше каналов" in w for w in r.warnings)


def test_parse_more_channels_warns():
    data = dg_ok()
    data["results"]["channels"].append({"alternatives": [{"transcript": "extra"}]})
    r = parse_deepgram_multichannel_response(
        data=data, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert len(r.channels) == 2
    assert any("лишние каналы" in w for w in r.warnings)


def test_parse_transcript_without_words_single_segment():
    data = {"metadata": {"duration": 1.0},
            "results": {"channels": [
                {"alternatives": [{"transcript": "только текст", "confidence": 0.7}]},
                {"alternatives": [{"transcript": "", "words": []}]}]}}
    r = parse_deepgram_multichannel_response(
        data=data, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert r.channels[0].segments_count == 1
    assert r.channels[0].segments[0].text == "только текст"


def test_parse_malformed_no_crash():
    r = parse_deepgram_multichannel_response(
        data={}, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert r.channels_count == 2
    assert all(c.transcript == "" for c in r.channels)


def test_parse_invalid_numbers_ignored():
    data = {"results": {"channels": [
        {"alternatives": [{"transcript": "x", "confidence": 2.5, "words": [
            {"word": "ok", "start": 0.1, "end": 0.5, "confidence": 0.9},
            {"word": "boolstart", "start": True, "end": 1.0},          # bool → skip
            {"word": "nanstart", "start": float("nan"), "end": 1.0},   # NaN → skip
            {"word": "neg", "start": -1.0, "end": 0.5},                # negative → skip
            {"word": "rev", "start": 2.0, "end": 1.0},                 # end<start → skip
        ]}]},
        {"alternatives": [{"transcript": ""}]}]}}
    r = parse_deepgram_multichannel_response(
        data=data, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert r.channels[0].words_count == 1                  # только валидное слово
    # confidence clamped 0..1
    assert r.channels[0].average_confidence is not None and 0.0 <= r.channels[0].average_confidence <= 1.0


def test_parse_stable_segment_ids():
    r1 = parse_deepgram_multichannel_response(
        data=dg_ok(), expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    r2 = parse_deepgram_multichannel_response(
        data=dg_ok(), expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    ids1 = [s.segment_id for s in r1.chronological_segments]
    ids2 = [s.segment_id for s in r2.chronological_segments]
    assert ids1 == ids2
    assert all(s.startswith("batch:") for s in ids1)


def test_parse_negative_duration_clamped():
    data = dg_ok()
    data["metadata"]["duration"] = -5.0           # враждебное/битое значение
    r = parse_deepgram_multichannel_response(
        data=data, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert r.duration_ms == 0                       # не отрицательное


def test_parse_word_grouping_by_gap():
    # нет utterances → группировка по gap > 1с
    data = {"results": {"channels": [
        {"alternatives": [{"transcript": "a b", "words": [
            {"word": "a", "start": 0.0, "end": 0.3, "confidence": 0.9},
            {"word": "b", "start": 2.0, "end": 2.3, "confidence": 0.9},   # gap 1.7с
        ]}]},
        {"alternatives": [{"transcript": ""}]}]}}
    r = parse_deepgram_multichannel_response(
        data=data, expected_channels=2, channel_mapping=MAPPING, model="nova-3", language="ru")
    assert r.channels[0].segments_count == 2


# ============================ adapter (httpx MockTransport) ============================

def _wav(channels=2, samples=10):
    header = build_pcm16_wav_header(sample_rate=16000, channels=channels, samples_per_channel=samples)
    return header + b"\x00" * (samples * channels * 2)


def _provider(handler, *, max_response_bytes=10_000_000, key="SECRET-KEY"):
    return DeepgramMultiChannelBatchProvider(
        api_key=key, base_url="https://api.deepgram.com/v1/listen",
        max_response_bytes=max_response_bytes, transport=httpx.MockTransport(handler))


async def test_adapter_success_and_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["ct"] = request.headers.get("content-type")
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.content
        return httpx.Response(200, json=dg_ok())

    r = await _provider(handler).transcribe(
        wav_bytes=_wav(), channel_count=2, channel_mapping=MAPPING,
        language="ru", model="nova-3", timeout_seconds=30)
    assert r.channels_count == 2
    assert "multichannel=true" in captured["url"]
    assert "model=nova-3" in captured["url"] and "language=ru" in captured["url"]
    assert captured["ct"] == "audio/wav"
    assert captured["auth"] == "Token SECRET-KEY"
    assert captured["body"][:4] == b"RIFF"                 # WAV отправлен
    # channel count закодирован в WAV-заголовке (offset 22)
    assert captured["body"][22] == 2


async def test_adapter_401_auth_no_key_leak():
    def handler(request):
        return httpx.Response(401, json={"err": "unauthorized"})
    with pytest.raises(MultiChannelBatchSttError) as ei:
        await _provider(handler, key="SUPER-SECRET").transcribe(
            wav_bytes=_wav(), channel_count=2, channel_mapping=MAPPING,
            language="ru", model="nova-3", timeout_seconds=30)
    assert ei.value.code == "PROVIDER_AUTH" and ei.value.retryable is False
    assert "SUPER-SECRET" not in str(ei.value)


async def test_adapter_429_rate_limit():
    def handler(request):
        return httpx.Response(429, text="slow down")
    with pytest.raises(MultiChannelBatchSttError) as ei:
        await _provider(handler).transcribe(
            wav_bytes=_wav(), channel_count=2, channel_mapping=MAPPING,
            language="ru", model="nova-3", timeout_seconds=30)
    assert ei.value.code == "PROVIDER_RATE_LIMIT" and ei.value.retryable is True


async def test_adapter_5xx_unavailable():
    def handler(request):
        return httpx.Response(503, text="down")
    with pytest.raises(MultiChannelBatchSttError) as ei:
        await _provider(handler).transcribe(
            wav_bytes=_wav(), channel_count=2, channel_mapping=MAPPING,
            language="ru", model="nova-3", timeout_seconds=30)
    assert ei.value.code == "PROVIDER_UNAVAILABLE" and ei.value.retryable is True


async def test_adapter_timeout():
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)
    with pytest.raises(MultiChannelBatchSttError) as ei:
        await _provider(handler).transcribe(
            wav_bytes=_wav(), channel_count=2, channel_mapping=MAPPING,
            language="ru", model="nova-3", timeout_seconds=30)
    assert ei.value.code == "PROVIDER_TIMEOUT" and ei.value.retryable is True


async def test_adapter_response_too_large():
    def handler(request):
        return httpx.Response(200, content=b"x" * 5000)
    with pytest.raises(MultiChannelBatchSttError) as ei:
        await _provider(handler, max_response_bytes=100).transcribe(
            wav_bytes=_wav(), channel_count=2, channel_mapping=MAPPING,
            language="ru", model="nova-3", timeout_seconds=30)
    assert ei.value.code == "PROVIDER_RESPONSE_TOO_LARGE"


async def test_adapter_malformed_json():
    def handler(request):
        return httpx.Response(200, content=b"not json")
    with pytest.raises(MultiChannelBatchSttError) as ei:
        await _provider(handler).transcribe(
            wav_bytes=_wav(), channel_count=2, channel_mapping=MAPPING,
            language="ru", model="nova-3", timeout_seconds=30)
    assert ei.value.code == "PROVIDER_BAD_RESPONSE"
