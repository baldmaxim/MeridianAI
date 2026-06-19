"""Тесты Deepgram realtime multichannel adapter + pure parser (Этап 9.6)."""

import asyncio
import json

import pytest

from app.services.realtime_multi_channel_provider import RealtimeMultiChannelProviderError
from app.services.deepgram_realtime_multichannel import (
    DeepgramRealtimeMultichannelProvider,
    parse_deepgram_realtime_multichannel_message,
)


def results_msg(channel_index, transcript, *, is_final=True, speech_final=False,
                words=None, start=1.0, duration=0.5):
    return {
        "type": "Results",
        "channel_index": channel_index,
        "channel": {"alternatives": [{"transcript": transcript, "confidence": 0.9,
                                       "words": words or []}]},
        "start": start, "duration": duration,
        "is_final": is_final, "speech_final": speech_final,
    }


# ============================ parser ============================

def test_parse_valid_channel_0():
    m = results_msg([0, 2], "привет", words=[
        {"word": "привет", "punctuated_word": "Привет", "start": 1.0, "end": 1.4, "confidence": 0.9}])
    r = parse_deepgram_realtime_multichannel_message(m, expected_channels=2)
    assert r is not None
    assert r.channel_index == 0 and r.channels_count == 2
    assert r.transcript == "привет" and r.is_final is True
    assert len(r.words) == 1 and r.words[0].text == "Привет"


def test_parse_valid_channel_1():
    r = parse_deepgram_realtime_multichannel_message(results_msg([1, 2], "да"), expected_channels=2)
    assert r is not None and r.channel_index == 1


def test_parse_channel_index_not_array():
    assert parse_deepgram_realtime_multichannel_message(
        results_msg(0, "x"), expected_channels=2) is None


def test_parse_wrong_total_channels():
    assert parse_deepgram_realtime_multichannel_message(
        results_msg([0, 3], "x"), expected_channels=2) is None


def test_parse_out_of_range_channel():
    assert parse_deepgram_realtime_multichannel_message(
        results_msg([2, 2], "x"), expected_channels=2) is None


def test_parse_bool_channel_index_rejected():
    assert parse_deepgram_realtime_multichannel_message(
        results_msg([True, 2], "x"), expected_channels=2) is None


def test_parse_metadata_and_utterance_end_ignored():
    assert parse_deepgram_realtime_multichannel_message(
        {"type": "Metadata", "request_id": "r"}, expected_channels=2) is None
    assert parse_deepgram_realtime_multichannel_message(
        {"type": "UtteranceEnd"}, expected_channels=2) is None


def test_parse_malformed_words_skipped():
    m = results_msg([0, 2], "x", words=[
        {"word": "ok", "start": 1.0, "end": 1.2, "confidence": 0.9},
        {"word": "boolstart", "start": True, "end": 1.4},        # bool → skip
        {"word": "nan", "start": float("nan"), "end": 1.4},      # NaN → skip
        {"word": "neg", "start": -1.0, "end": 0.2},              # negative → skip
        {"word": "rev", "start": 2.0, "end": 1.0},               # end<start → skip
    ])
    r = parse_deepgram_realtime_multichannel_message(m, expected_channels=2)
    assert r is not None and len(r.words) == 1


def test_parse_confidence_clamped():
    m = results_msg([0, 2], "x")
    m["channel"]["alternatives"][0]["confidence"] = 2.5
    r = parse_deepgram_realtime_multichannel_message(m, expected_channels=2)
    assert r.confidence is not None and 0.0 <= r.confidence <= 1.0


def test_parse_interim_speech_final_flags():
    r = parse_deepgram_realtime_multichannel_message(
        results_msg([0, 2], "x", is_final=False), expected_channels=2)
    assert r.is_final is False
    r2 = parse_deepgram_realtime_multichannel_message(
        results_msg([0, 2], "x", is_final=True, speech_final=True), expected_channels=2)
    assert r2.speech_final is True


# ============================ adapter (mock ws) ============================

class FakeWS:
    def __init__(self, messages):
        self._messages = [json.dumps(m) for m in messages]
        self.sent = []
        self.closed = False

    def __aiter__(self):
        async def gen():
            for m in self._messages:
                yield m
        return gen()

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True


def _provider(connect_fn, key="SECRET-KEY"):
    return DeepgramRealtimeMultichannelProvider(
        api_key=key, base_url="wss://api.deepgram.com/v1/listen", connect_fn=connect_fn)


async def test_adapter_connect_query_and_results():
    captured = {}
    ws = FakeWS([results_msg([0, 2], "привет"), results_msg([1, 2], "да")])

    async def connect_fn(url, headers):
        captured["url"] = url
        captured["headers"] = headers
        return ws

    results = []

    async def on_result(r):
        results.append(r)

    async def on_error(e):
        results.append(("error", e))

    p = _provider(connect_fn)
    await p.connect(channel_count=2, sample_rate=16000, model="nova-3", language="ru",
                    on_result=on_result, on_error=on_error)
    await asyncio.sleep(0.05)
    await p.close(finalize=True)

    assert "encoding=linear16" in captured["url"]
    assert "sample_rate=16000" in captured["url"]
    assert "channels=2" in captured["url"]
    assert "multichannel=true" in captured["url"]
    assert "model=nova-3" in captured["url"] and "language=ru" in captured["url"]
    assert "interim_results=true" in captured["url"]
    assert captured["headers"] == [("Authorization", "Token SECRET-KEY")]
    assert "SECRET-KEY" not in captured["url"]            # ключ только в header
    chans = [r.channel_index for r in results if hasattr(r, "channel_index")]
    assert chans == [0, 1]
    # CloseStream отправлен текстом
    assert any(isinstance(s, str) and "CloseStream" in s for s in ws.sent)
    assert ws.closed is True


async def test_adapter_send_audio_binary_and_keepalive():
    ws = FakeWS([])

    async def connect_fn(url, headers):
        return ws

    p = _provider(connect_fn)
    await p.connect(channel_count=2, sample_rate=16000, model="nova-3", language="ru",
                    on_result=lambda r: asyncio.sleep(0), on_error=lambda e: asyncio.sleep(0))
    await p.send_audio(b"\x01\x02\x03\x04")
    await p.keepalive()
    assert b"\x01\x02\x03\x04" in ws.sent                 # бинарный PCM
    assert any(isinstance(s, str) and "KeepAlive" in s for s in ws.sent)
    await p.close(finalize=False)


async def test_adapter_auth_error_no_key_leak():
    async def connect_fn(url, headers):
        raise Exception("server rejected WebSocket connection: HTTP 401")

    p = _provider(connect_fn, key="SUPER-SECRET")
    with pytest.raises(RealtimeMultiChannelProviderError) as ei:
        await p.connect(channel_count=2, sample_rate=16000, model="nova-3", language="ru",
                        on_result=lambda r: asyncio.sleep(0), on_error=lambda e: asyncio.sleep(0))
    assert ei.value.code == "PROVIDER_AUTH"
    assert "SUPER-SECRET" not in str(ei.value)


async def test_adapter_connect_failed_generic():
    async def connect_fn(url, headers):
        raise Exception("connection refused")

    p = _provider(connect_fn)
    with pytest.raises(RealtimeMultiChannelProviderError) as ei:
        await p.connect(channel_count=2, sample_rate=16000, model="nova-3", language="ru",
                        on_result=lambda r: asyncio.sleep(0), on_error=lambda e: asyncio.sleep(0))
    assert ei.value.code == "PROVIDER_CONNECT_FAILED"
