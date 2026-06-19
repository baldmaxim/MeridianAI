"""Deepgram realtime multichannel adapter + pure parser (Этап 9.6).

Один provider-сокет на одну shadow-сессию. interleaved PCM16 шлётся бинарно (без WAV header).
API key только в Authorization header, не хранится в state и не логируется. Без reconnect.
"""

import asyncio
import dataclasses
import json
import logging
import urllib.parse
from typing import Awaitable, Callable

import websockets

from .deepgram_multi_channel_batch import _conf, _text, _ts
from .realtime_multi_channel_provider import (
    ERR_AUTH,
    ERR_CONNECT_FAILED,
    ERR_DISCONNECTED,
    ERR_PROTOCOL,
    RealtimeMultiChannelProviderError,
    RealtimeProviderResult,
    RealtimeProviderWord,
)

logger = logging.getLogger("meridian.dg_realtime")


def _int_no_bool(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def parse_deepgram_realtime_multichannel_message(
    data: dict, *, expected_channels: int,
) -> RealtimeProviderResult | None:
    """Pure-парсер одного Deepgram realtime сообщения. Только валидные Results → result.

    Metadata/UtteranceEnd/SpeechStarted/прочее → None. JSON не доверяем.
    channel_index ОБЯЗАТЕЛЬНО [current, total]; speaker как channel НЕ используем.
    """
    if not isinstance(data, dict):
        return None
    if data.get("type") not in ("Results", None):
        return None  # Metadata / UtteranceEnd / SpeechStarted и т.п.

    ci_arr = data.get("channel_index")
    if not isinstance(ci_arr, (list, tuple)) or len(ci_arr) != 2:
        return None
    current = _int_no_bool(ci_arr[0])
    total = _int_no_bool(ci_arr[1])
    if current is None or total is None:
        return None
    if total != expected_channels or not (0 <= current < expected_channels):
        return None

    channel = data.get("channel")
    if not isinstance(channel, dict):
        return None
    alts = channel.get("alternatives")
    if not isinstance(alts, list) or not alts or not isinstance(alts[0], dict):
        return None
    alt = alts[0]
    transcript = _text(alt.get("transcript")).strip()

    start = _ts(data.get("start"))
    duration = _ts(data.get("duration"))
    if start is None:
        start = 0.0
    if duration is None:
        duration = 0.0

    words = []
    raw_words = alt.get("words")
    if isinstance(raw_words, list):
        for w in raw_words:
            if not isinstance(w, dict):
                continue
            ws_ = _ts(w.get("start"))
            we_ = _ts(w.get("end"))
            if ws_ is None or we_ is None or we_ < ws_:
                continue
            text = _text(w.get("punctuated_word")) or _text(w.get("word"))
            if not text:
                continue
            words.append(RealtimeProviderWord(
                text=text, start=ws_, end=we_, confidence=_conf(w.get("confidence")),
                punctuated_word=_text(w.get("punctuated_word")) or None,
            ))

    return RealtimeProviderResult(
        channel_index=current, channels_count=total, transcript=transcript,
        confidence=_conf(alt.get("confidence")), start=start, duration=duration,
        is_final=bool(data.get("is_final", False)),
        speech_final=bool(data.get("speech_final", False)),
        from_finalize=bool(data.get("from_finalize", False)),
        words=tuple(words), request_id=None,
    )


async def _default_connect(url: str, headers: list):
    return await websockets.connect(url, additional_headers=headers)


class DeepgramRealtimeMultichannelProvider:
    name = "deepgram"

    def __init__(self, *, api_key: str, base_url: str, keepalive_seconds: int = 4,
                 close_timeout_seconds: int = 8, connect_fn: Callable | None = None):
        self._api_key = api_key
        self._base_url = base_url
        self._keepalive_seconds = keepalive_seconds
        self._close_timeout = close_timeout_seconds
        self._connect_fn = connect_fn or _default_connect
        self._ws = None
        self._expected_channels = 0
        self._recv_task: asyncio.Task | None = None
        self._request_id: str | None = None
        self._on_result = None
        self._on_error = None

    async def connect(self, *, channel_count: int, sample_rate: int, model: str, language: str,
                      on_result: Callable[[RealtimeProviderResult], Awaitable[None]],
                      on_error: Callable[[Exception], Awaitable[None]]) -> None:
        self._expected_channels = channel_count
        self._on_result = on_result
        self._on_error = on_error
        params = {
            "encoding": "linear16", "sample_rate": sample_rate, "channels": channel_count,
            "multichannel": "true", "model": model, "language": language,
            "interim_results": "true", "punctuate": "true", "smart_format": "true",
            "vad_events": "true", "utterance_end_ms": 1500,
        }
        url = f"{self._base_url}?{urllib.parse.urlencode(params)}"
        headers = [("Authorization", f"Token {self._api_key}")]
        try:
            self._ws = await self._connect_fn(url, headers)
        except Exception as e:
            code = ERR_AUTH if ("401" in str(e) or "403" in str(e)) else ERR_CONNECT_FAILED
            raise RealtimeMultiChannelProviderError(code, "Не удалось подключиться к STT-провайдеру",
                                                    retryable=(code != ERR_AUTH))
        self._recv_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                except (ValueError, TypeError):
                    continue
                if not isinstance(data, dict):
                    continue
                mtype = data.get("type")
                if mtype == "Metadata":
                    rid = data.get("request_id")
                    if isinstance(rid, str):
                        self._request_id = rid
                    continue
                if mtype in ("Error", "error"):
                    if self._on_error:
                        await self._on_error(RealtimeMultiChannelProviderError(
                            ERR_PROTOCOL, "Ошибка протокола STT-провайдера"))
                    continue
                result = parse_deepgram_realtime_multichannel_message(
                    data, expected_channels=self._expected_channels)
                if result is None:
                    continue
                if self._request_id and result.request_id is None:
                    result = dataclasses.replace(result, request_id=self._request_id)
                if self._on_result:
                    await self._on_result(result)
        except websockets.exceptions.ConnectionClosed:
            if self._on_error:
                await self._on_error(RealtimeMultiChannelProviderError(
                    ERR_DISCONNECTED, "Соединение со STT-провайдером закрыто", retryable=True))
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._on_error:
                await self._on_error(RealtimeMultiChannelProviderError(
                    ERR_PROTOCOL, "Сбой обработки ответа STT-провайдера"))

    async def send_audio(self, pcm16_interleaved: bytes) -> None:
        if self._ws is None:
            raise RealtimeMultiChannelProviderError(ERR_DISCONNECTED, "Нет соединения с провайдером")
        try:
            await self._ws.send(pcm16_interleaved)
        except websockets.exceptions.ConnectionClosed:
            raise RealtimeMultiChannelProviderError(ERR_DISCONNECTED, "Соединение закрыто", retryable=True)

    async def keepalive(self) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "KeepAlive"}))
        except Exception:
            pass

    async def close(self, *, finalize: bool = True) -> None:
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                if finalize:
                    await ws.send(json.dumps({"type": "CloseStream"}))
                await asyncio.wait_for(ws.close(), timeout=self._close_timeout)
            except asyncio.TimeoutError:
                try:
                    await ws.close()
                except Exception:
                    pass
            except Exception:
                pass
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
            self._recv_task = None

    @property
    def request_id(self) -> str | None:
        return self._request_id
