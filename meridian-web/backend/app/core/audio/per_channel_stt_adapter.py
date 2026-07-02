"""Per-channel STT provider adapter (Этап 18): безопасный реальный STT для canary.

Подключает существующий ElevenLabs batch STT ТОЛЬКО для per-channel canary. По умолчанию provider
="noop" (без внешних вызовов). Bounded: timeout + per-meeting budget + in-memory LRU cache. Никогда
не пишет audio на диск, не логирует raw text/audio, не хранит API-ключи в repr/logs. channel_{index}
— техническая зона записи, не сторона.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import time
import wave
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import BaseModel

from ..context.per_channel_stt_policy import PerChannelSttRuntimeConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # избегаем цикла per_channel_stt <-> adapter
    from .per_channel_stt import PerChannelAudioSegment

_ALLOWED_PROVIDERS = {"noop", "elevenlabs_batch", "existing_batch"}

AdapterErrorKind = Literal[
    "adapter_unavailable", "api_key_missing", "unknown_provider", "timeout",
    "provider_error", "empty_text", "audio_too_long", "audio_too_large",
    "budget_exhausted", "invalid_audio", "exception",
]


class PerChannelSttAdapterResult(BaseModel):
    text: str = ""
    text_hash: str = ""
    confidence: Optional[float] = None
    language_code: Optional[str] = None
    provider: str = "unknown"
    model_id: Optional[str] = None
    latency_ms: Optional[int] = None
    error_kind: Optional[str] = None
    cached: bool = False

    def __repr__(self) -> str:  # без raw text/audio
        return (f"PerChannelSttAdapterResult(provider={self.provider!r}, "
                f"has_text={bool(self.text)}, error_kind={self.error_kind!r}, cached={self.cached})")


class PerChannelSttAdapterError(BaseModel):
    error_kind: AdapterErrorKind
    message: Optional[str] = None


# --------------------------------------------------------------------------- helpers

def pcm16_mono_to_wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """In-memory PCM16 mono → WAV bytes. Без temp-файлов."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm)
    buf.seek(0)
    return buf.read()


def normalize_stt_text(text: str) -> str:
    """Безопасная нормализация STT-текста: схлопнуть пробелы, обрезать. Текст не логируется."""
    if not text:
        return ""
    return " ".join(str(text).split()).strip()


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def hash_audio_for_cache(pcm: bytes, sample_rate: int, provider: str, model_id: str,
                         language_code: str) -> str:
    """Стабильный ключ кэша по аудио+provider/model/lang. Меняется при смене любого из них."""
    h = hashlib.sha256()
    h.update(pcm or b"")
    h.update(f"|{int(sample_rate)}|{provider}|{model_id}|{language_code}".encode("utf-8"))
    return h.hexdigest()[:24]


# --------------------------------------------------------------------------- cache + budget

class PerChannelSttCache:
    """In-memory LRU кэш результатов STT (только в памяти, без диска)."""

    def __init__(self, max_entries: int):
        self.max_entries = max(0, int(max_entries))
        self._d: "OrderedDict[str, PerChannelSttAdapterResult]" = OrderedDict()
        self.cache_hit_count = 0
        self.cache_miss_count = 0
        self.cache_eviction_count = 0

    def get(self, key: str) -> Optional[PerChannelSttAdapterResult]:
        if self.max_entries <= 0 or key not in self._d:
            self.cache_miss_count += 1
            return None
        self._d.move_to_end(key)
        self.cache_hit_count += 1
        cached = self._d[key]
        return cached.model_copy(update={"cached": True})

    def set(self, key: str, result: PerChannelSttAdapterResult) -> None:
        if self.max_entries <= 0:
            return
        self._d[key] = result.model_copy(update={"cached": False})
        self._d.move_to_end(key)
        while len(self._d) > self.max_entries:
            self._d.popitem(last=False)
            self.cache_eviction_count += 1

    def clear(self) -> None:
        self._d.clear()


class PerChannelSttBudget:
    """Per-meeting бюджет provider-вызовов (защита стоимости)."""

    def __init__(self, max_calls: int, max_audio_seconds: float):
        self.max_calls = int(max_calls)
        self.max_audio_seconds = float(max_audio_seconds)
        self.calls_used = 0
        self.audio_seconds_used = 0.0
        self.exhausted_count = 0

    def update_limits(self, max_calls: int, max_audio_seconds: float) -> None:
        self.max_calls = int(max_calls)
        self.max_audio_seconds = float(max_audio_seconds)

    def allow(self, segment_duration_ms: int) -> bool:
        if self.max_calls <= 0 or self.max_audio_seconds <= 0:
            self.exhausted_count += 1
            return False
        dur_s = max(0, int(segment_duration_ms)) / 1000.0
        if self.calls_used >= self.max_calls or (self.audio_seconds_used + dur_s) > self.max_audio_seconds:
            self.exhausted_count += 1
            return False
        return True

    def consume(self, segment_duration_ms: int) -> None:
        self.calls_used += 1
        self.audio_seconds_used += max(0, int(segment_duration_ms)) / 1000.0


# --------------------------------------------------------------------------- adapters

class NoopPerChannelSttAdapter:
    """Безопасный дефолт: внешних вызовов нет. Возвращает None → adapter_unavailable."""

    provider = "noop"
    is_noop = True

    async def transcribe_segment(self, segment: "PerChannelAudioSegment",
                                 config: PerChannelSttRuntimeConfig) -> Optional[PerChannelSttAdapterResult]:
        return None


class StaticErrorPerChannelSttAdapter:
    """Адаптер, всегда возвращающий безопасную ошибку (unknown_provider/adapter_unavailable)."""

    def __init__(self, error_kind: str, provider: str = "unknown"):
        self._error_kind = error_kind
        self.provider = provider

    async def transcribe_segment(self, segment, config) -> PerChannelSttAdapterResult:
        return PerChannelSttAdapterResult(provider=self.provider, error_kind=self._error_kind)


def _default_service_factory(api_key: str, language_code: str, model_id: str):
    from ..transcription.batch_service import BatchTranscriptionService
    return BatchTranscriptionService(api_key=api_key, language_code=language_code, model_id=model_id)


def _default_keyterms():
    try:
        from ..transcription.service import BOOSTED_KEYWORDS
        return list(BOOSTED_KEYWORDS)
    except Exception:  # noqa: BLE001
        return None


class ElevenLabsBatchPerChannelSttAdapter:
    """Per-channel STT через существующий BatchTranscriptionService (ElevenLabs Scribe).

    Безопасно: WAV in-memory; blocking HTTP вынесен в поток (не блокирует WS-loop); timeout; без
    диаризации (diarize=False) — per-channel сегмент = один источник; raw text/ответ не логируются.
    API-ключ держится только в адаптере (не в repr/logs/snapshot).
    """

    def __init__(self, *, api_key: Optional[str], provider: str = "elevenlabs_batch",
                 service_factory=None, keyterms=None):
        self._api_key = api_key
        self.provider = provider
        self._service_factory = service_factory or _default_service_factory
        self._keyterms = keyterms if keyterms is not None else _default_keyterms()

    def __repr__(self) -> str:  # без api_key
        return f"ElevenLabsBatchPerChannelSttAdapter(provider={self.provider!r}, has_key={bool(self._api_key)})"

    async def transcribe_segment(self, segment: "PerChannelAudioSegment",
                                 config: PerChannelSttRuntimeConfig) -> PerChannelSttAdapterResult:
        if not self._api_key:
            return PerChannelSttAdapterResult(provider=self.provider, error_kind="api_key_missing")
        try:
            wav = pcm16_mono_to_wav_bytes(segment.pcm16_mono, segment.sample_rate)
        except Exception:  # noqa: BLE001
            return PerChannelSttAdapterResult(provider=self.provider, error_kind="invalid_audio")
        if len(wav) > config.max_wav_bytes:
            return PerChannelSttAdapterResult(provider=self.provider, error_kind="audio_too_large")

        model_id = config.model_id or "scribe_v2"
        language_code = config.language_code or "ru"
        keyterms = self._keyterms
        api_key = self._api_key
        factory = self._service_factory
        # Этап 19: ограничиваем HTTP-таймаут провайдера тем же bounded значением, чтобы orphan-поток
        # не жил дольше asyncio-таймаута (1..120с).
        bounded_timeout = min(max(float(config.timeout_seconds), 1.0), 120.0)

        def _blocking() -> str:
            # Отдельный event loop в worker-потоке: service.transcribe — async, но внутри блокирующий
            # requests.post. Не блокируем основной loop. Возвращаем объединённый text.
            service = factory(api_key, language_code, model_id)
            segments = asyncio.run(service.transcribe(
                wav, diarize=False, keyterms=keyterms, request_timeout=bounded_timeout))
            return " ".join((getattr(s, "text", "") or "") for s in (segments or [])).strip()

        t0 = time.perf_counter()
        try:
            raw_text = await asyncio.wait_for(asyncio.to_thread(_blocking), timeout=bounded_timeout)
        except asyncio.TimeoutError:
            return PerChannelSttAdapterResult(provider=self.provider, error_kind="timeout")
        except Exception as e:  # noqa: BLE001 — провайдерская ошибка не ломает поток (raw не логируем)
            from ..transcription.provider_error_safety import safe_provider_error_summary
            logger.debug("[PerChannelStt] provider error: %s",
                         safe_provider_error_summary(e, provider=self.provider))
            return PerChannelSttAdapterResult(provider=self.provider, error_kind="provider_error")
        latency_ms = int((time.perf_counter() - t0) * 1000)

        text = normalize_stt_text(raw_text)
        if not text:
            return PerChannelSttAdapterResult(provider=self.provider, error_kind="empty_text",
                                              latency_ms=latency_ms)
        return PerChannelSttAdapterResult(
            text=text, text_hash=hash_text(text), confidence=None, language_code=language_code,
            provider=self.provider, model_id=model_id, latency_ms=latency_ms)


def build_per_channel_stt_adapter(config: PerChannelSttRuntimeConfig, *, api_key: Optional[str] = None,
                                  service_factory=None, keyterms=None) -> Any:
    """Фабрика адаптера по config.provider. noop → Noop; batch → ElevenLabs (key проверяется при
    вызове); неизвестный provider → StaticError(unknown_provider). API-ключ только из аргумента."""
    provider = (config.provider or "noop").lower()
    if provider == "noop":
        return NoopPerChannelSttAdapter()
    if provider in ("elevenlabs_batch", "existing_batch"):
        return ElevenLabsBatchPerChannelSttAdapter(
            api_key=api_key, provider=provider, service_factory=service_factory, keyterms=keyterms)
    return StaticErrorPerChannelSttAdapter("unknown_provider", provider=provider)
