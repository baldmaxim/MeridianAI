"""Batch multi-channel STT — нормализованные domain-типы + provider abstraction (Этап 9.5).

Один канал WAV = один track. Provider (Deepgram prerecorded multichannel) распознаёт каждый
канал отдельно; результат — ТОЛЬКО диагностический кандидат: live transcript не заменяется,
ничего не сохраняется в БД/диск/S3, raw provider response целиком не хранится.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

BatchJobStatus = Literal[
    "queued", "preparing", "transcribing", "parsing", "comparing",
    "succeeded", "failed", "cancelled", "expired",
]


@dataclass(frozen=True)
class MultiChannelBatchWord:
    text: str
    start: float
    end: float
    channel_index: int
    confidence: float | None = None
    punctuated_word: str | None = None


@dataclass(frozen=True)
class MultiChannelBatchSegment:
    segment_id: str
    channel_index: int
    track_id: str
    channel_label: str
    side: str | None
    text: str
    start: float
    end: float
    confidence: float | None
    words: tuple = ()  # tuple[MultiChannelBatchWord, ...]


@dataclass(frozen=True)
class MultiChannelBatchChannel:
    channel_index: int
    track_id: str
    channel_label: str
    side: str | None
    source_kind: str
    generation: int
    transcript: str
    words_count: int
    segments_count: int
    average_confidence: float | None
    segments: tuple = ()    # tuple[MultiChannelBatchSegment, ...]
    warnings: tuple = ()


@dataclass(frozen=True)
class MultiChannelBatchResult:
    provider: str
    model: str
    language: str
    provider_request_id: str | None
    sample_rate: int
    channels_count: int
    duration_ms: int
    channels: tuple                  # tuple[MultiChannelBatchChannel, ...]
    chronological_segments: tuple    # tuple[MultiChannelBatchSegment, ...]
    combined_text: str
    warnings: tuple
    provider_meta: dict = field(default_factory=dict)  # ТОЛЬКО request_id/model/lang/duration/channels


class MultiChannelBatchSttError(RuntimeError):
    """Ошибка batch STT. Никогда не несёт API key / Authorization / response body / PCM / WAV."""

    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 provider_status: int | None = None):
        self.code = code
        self.retryable = retryable
        self.provider_status = provider_status
        super().__init__(message)


# коды ошибок
ERR_FEATURE_DISABLED = "FEATURE_DISABLED"
ERR_PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
ERR_UNSUPPORTED_PROVIDER = "UNSUPPORTED_PROVIDER"
ERR_INVALID_AUDIO = "INVALID_AUDIO"
ERR_INVALID_CHANNEL_COUNT = "INVALID_CHANNEL_COUNT"
ERR_PROVIDER_AUTH = "PROVIDER_AUTH"
ERR_PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
ERR_PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
ERR_PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
ERR_PROVIDER_BAD_RESPONSE = "PROVIDER_BAD_RESPONSE"
ERR_PROVIDER_RESPONSE_TOO_LARGE = "PROVIDER_RESPONSE_TOO_LARGE"
ERR_CANCELLED = "CANCELLED"
ERR_INTERNAL = "INTERNAL_ERROR"


class MultiChannelBatchProvider(Protocol):
    name: str

    async def transcribe(
        self,
        *,
        wav_bytes: bytes,
        channel_count: int,
        channel_mapping: list,
        language: str,
        model: str,
        timeout_seconds: int,
    ) -> MultiChannelBatchResult:
        ...
