"""Realtime multi-channel STT provider abstraction (Этап 9.6).

Отделяет live-сессию от конкретного провайдера (Deepgram realtime). Результаты приходят
ПОканально (channel_index). Ошибки никогда не несут API key / Authorization / raw response.
"""

from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol


@dataclass(frozen=True)
class RealtimeProviderWord:
    text: str
    start: float
    end: float
    confidence: float | None
    punctuated_word: str | None = None


@dataclass(frozen=True)
class RealtimeProviderResult:
    channel_index: int
    channels_count: int
    transcript: str
    confidence: float | None
    start: float
    duration: float
    is_final: bool
    speech_final: bool
    from_finalize: bool
    words: tuple = ()           # tuple[RealtimeProviderWord, ...]
    request_id: str | None = None


class RealtimeMultiChannelProviderError(RuntimeError):
    """Ошибка realtime-провайдера. Без API key / Authorization / response body / PCM."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


# коды ошибок
ERR_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
ERR_CONNECT_FAILED = "PROVIDER_CONNECT_FAILED"
ERR_AUTH = "PROVIDER_AUTH"
ERR_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
ERR_PROTOCOL = "PROVIDER_PROTOCOL"
ERR_BACKPRESSURE = "PROVIDER_BACKPRESSURE"
ERR_DISCONNECTED = "PROVIDER_DISCONNECTED"
ERR_TIMEOUT = "PROVIDER_TIMEOUT"
ERR_CLOSE_TIMEOUT = "PROVIDER_CLOSE_TIMEOUT"
ERR_BAD_RESPONSE = "PROVIDER_BAD_RESPONSE"


class RealtimeMultiChannelProvider(Protocol):
    name: str

    async def connect(
        self,
        *,
        channel_count: int,
        sample_rate: int,
        model: str,
        language: str,
        on_result: Callable[[RealtimeProviderResult], Awaitable[None]],
        on_error: Callable[[Exception], Awaitable[None]],
    ) -> None:
        ...

    async def send_audio(self, pcm16_interleaved: bytes) -> None:
        ...

    async def keepalive(self) -> None:
        ...

    async def close(self, *, finalize: bool = True) -> None:
        ...
