"""Per-channel STT pipeline (Этап 17): MAUD2 v2 каналы → VAD/dominance сегменты → STT → source candidates.

Opt-in canary. По умолчанию выключен/shadow. channel_{index} — техническая зона записи, НЕ сторона
и НЕ личность. НЕ заменяет legacy mono STT. НЕ выводит сторону. Raw audio/text не логируются и не
сохраняются на диск.
"""

import array
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel

from ..context.audio_frame_v2 import ParsedAudioFrameV2
from ..context.per_channel_stt_policy import PerChannelSttRuntimeConfig
from .per_channel_stt_adapter import (  # noqa: F401 — pcm16_mono_to_wav_bytes re-export для тестов
    NoopPerChannelSttAdapter,
    PerChannelSttBudget,
    PerChannelSttCache,
    hash_audio_for_cache,
    hash_text,
    normalize_stt_text,
    pcm16_mono_to_wav_bytes,
)

_EPS = 1e-9
_RATE_WINDOW_MS = 60000


# --------------------------------------------------------------------------- модели

@dataclass
class PerChannelAudioSegment:
    channel_index: int
    source_id: str
    channel_label: str
    start_ms: Optional[int]
    end_ms: Optional[int]
    duration_ms: int
    sample_rate: int
    pcm16_mono: bytes = field(repr=False)  # raw audio — НЕ в repr/лог
    rms: float = 0.0
    peak: float = 0.0
    dominance: float = 0.0
    frame_count: int = 0

    def __repr__(self) -> str:  # без raw audio
        return (f"PerChannelAudioSegment(channel_index={self.channel_index}, "
                f"duration_ms={self.duration_ms}, frames={self.frame_count}, "
                f"dominance={round(self.dominance, 3)}, pcm_bytes={len(self.pcm16_mono)})")


class PerChannelSttCandidate(BaseModel):
    text: str
    text_hash: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    audio_source_id: str
    channel_label: str
    source_is_isolated: bool = False
    source_kind: str = "multi_channel"
    attribution_source: str = "multi_source_segment"
    attribution_confidence: float = 0.0
    source: str = "per_channel_stt"
    channel_index: Optional[int] = None


class PerChannelSttStats(BaseModel):
    enabled: bool = False
    shadow_mode: bool = True
    provider: Optional[str] = None
    frame_count: int = 0
    segment_started_count: int = 0
    segment_finalized_count: int = 0
    segment_dropped_low_rms_count: int = 0
    segment_dropped_low_dominance_count: int = 0
    segment_dropped_rate_limit_count: int = 0
    transcribe_attempt_count: int = 0
    transcribe_success_count: int = 0
    transcribe_error_count: int = 0
    # Provider adapter counters (Этап 18)
    transcribe_timeout_count: int = 0
    transcribe_empty_text_count: int = 0
    transcribe_provider_error_count: int = 0
    transcribe_budget_exhausted_count: int = 0
    transcribe_cache_hit_count: int = 0
    transcribe_cache_miss_count: int = 0
    transcribe_audio_too_long_count: int = 0
    transcribe_audio_too_large_count: int = 0
    adapter_unavailable_count: int = 0
    # Budget/cost (Этап 20) — безопасные агрегаты, без raw audio
    provider_calls_used: int = 0
    provider_audio_seconds_used: float = 0.0
    candidate_emit_count: int = 0
    candidate_shadow_suppressed_count: int = 0
    max_channels_seen: int = 0
    active_channel_count: int = 0
    average_dominance: Optional[float] = None
    average_transcribe_latency_ms: Optional[float] = None
    last_error_kind: Optional[str] = None


# --------------------------------------------------------------------------- helpers

def _deinterleave_channel(payload: bytes, channels: int, c: int) -> bytes:
    """Вытащить mono PCM16 канала c из interleaved payload."""
    n = (len(payload) // 2)
    a = array.array("h")
    a.frombytes(bytes(payload[: n * 2]))
    if sys.byteorder != "little":
        a.byteswap()
    ch = array.array("h", a[c::channels])
    if sys.byteorder != "little":
        ch.byteswap()
    return ch.tobytes()


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- открытый сегмент

@dataclass
class _OpenSegment:
    start_ms: int
    last_active_end_ms: int
    pcm: bytearray
    frames: int = 0
    rms_sum: float = 0.0
    dom_sum: float = 0.0
    peak: float = 0.0
    silence_ms: int = 0


class PerChannelSttPipeline:
    """Сегментация по каналам + транскрипция + сборка source candidate payload. Без побочных
    эффектов на legacy STT. Raw audio не пишется на диск."""

    def __init__(self, config: PerChannelSttRuntimeConfig, stt_adapter: Any = None):
        self.config = config
        self.adapter = stt_adapter if stt_adapter is not None else NoopPerChannelSttAdapter()
        self._cache = PerChannelSttCache(config.cache_max_entries)
        self._budget = PerChannelSttBudget(
            config.max_provider_calls_per_meeting, config.max_provider_audio_seconds_per_meeting)
        self.clear()

    def update_config(self, config: PerChannelSttRuntimeConfig) -> None:
        self.config = config
        self._budget.update_limits(
            config.max_provider_calls_per_meeting, config.max_provider_audio_seconds_per_meeting)
        if self._cache.max_entries != config.cache_max_entries:
            self._cache = PerChannelSttCache(config.cache_max_entries)

    def set_adapter(self, adapter: Any) -> None:
        self.adapter = adapter if adapter is not None else NoopPerChannelSttAdapter()

    def clear(self) -> None:
        self._clock_ms = 0
        self._clock_seeded = False
        self._open: dict[int, _OpenSegment] = {}
        self._active_channels: set[int] = set()
        self._emit_times: list[int] = []
        self._dom_values: list[float] = []
        self._latencies: list[float] = []
        self._cache.clear()
        self._stats = PerChannelSttStats(
            enabled=self.config.enabled, shadow_mode=self.config.shadow_mode)

    # ---- ingest / segmentation ----

    def ingest_frame(self, parsed_frame: ParsedAudioFrameV2) -> list[PerChannelAudioSegment]:
        """Обработать v2 кадр: обновить per-channel сегменты, вернуть готовые (прошедшие гейты)."""
        h = parsed_frame.header
        channels = min(int(h.channels), int(self.config.max_channels))
        if channels < 1:
            return []
        self._stats.frame_count += 1
        self._stats.max_channels_seen = max(self._stats.max_channels_seen, int(h.channels))

        frame_dur = int(parsed_frame.duration_ms_estimate) or 0
        if not self._clock_seeded:
            base = h.created_at_ms if isinstance(h.created_at_ms, int) else 0
            self._clock_ms = base
            self._clock_seeded = True
        clock_start = self._clock_ms
        clock_end = self._clock_ms + frame_dur
        self._clock_ms = clock_end

        rms_all = parsed_frame.rms_by_channel or []
        peak_all = parsed_frame.peak_by_channel or []
        total_rms = sum(rms_all[:channels]) + _EPS
        finalized: list[PerChannelAudioSegment] = []

        for c in range(channels):
            rms_c = float(rms_all[c]) if c < len(rms_all) else 0.0
            peak_c = float(peak_all[c]) if c < len(peak_all) else 0.0
            dom_c = rms_c / total_rms
            active = rms_c >= self.config.min_rms and dom_c >= self.config.min_dominance

            seg = self._open.get(c)
            if active:
                self._active_channels.add(c)
                if seg is None:
                    seg = _OpenSegment(start_ms=clock_start, last_active_end_ms=clock_end, pcm=bytearray())
                    self._open[c] = seg
                    self._stats.segment_started_count += 1
                seg.pcm += _deinterleave_channel(parsed_frame.payload, int(h.channels), c)
                seg.frames += 1
                seg.rms_sum += rms_c
                seg.dom_sum += dom_c
                seg.peak = max(seg.peak, peak_c)
                seg.last_active_end_ms = clock_end
                seg.silence_ms = 0
                if clock_end - seg.start_ms >= self.config.max_segment_ms:
                    done = self._finalize_channel(c, int(h.sample_rate))
                    if done is not None:
                        finalized.append(done)
            elif seg is not None:
                seg.silence_ms += frame_dur
                if seg.silence_ms >= self.config.end_silence_ms:
                    done = self._finalize_channel(c, int(h.sample_rate))
                    if done is not None:
                        finalized.append(done)

        return finalized

    def finalize_due_segments(self, now_ms: Optional[int] = None) -> list[PerChannelAudioSegment]:
        """Принудительно завершить все открытые сегменты (например, при остановке)."""
        out: list[PerChannelAudioSegment] = []
        for c in list(self._open.keys()):
            done = self._finalize_channel(c, self._last_sample_rate())
            if done is not None:
                out.append(done)
        return out

    def _last_sample_rate(self) -> int:
        return 16000

    def _finalize_channel(self, c: int, sample_rate: int) -> Optional[PerChannelAudioSegment]:
        seg = self._open.pop(c, None)
        if seg is None:
            return None
        duration = max(0, seg.last_active_end_ms - seg.start_ms)
        if duration < self.config.min_segment_ms:
            # Слишком короткий blip — НЕ считается сегментом: учтён в segment_started_count, но не в
            # segment_finalized_count (started − finalized = короткие + ещё открытые). Отдельный
            # drop-счётчик не вводим — модель PerChannelSttStats фиксирована (Этап 17).
            return None
        avg_rms = seg.rms_sum / seg.frames if seg.frames else 0.0
        avg_dom = seg.dom_sum / seg.frames if seg.frames else 0.0
        self._stats.segment_finalized_count += 1
        self._dom_values.append(round(avg_dom, 4))

        if avg_dom < self.config.min_dominance:
            self._stats.segment_dropped_low_dominance_count += 1
            return None
        if avg_rms < self.config.min_rms:
            self._stats.segment_dropped_low_rms_count += 1
            return None
        # rate limit (rolling 60s по внутренним часам)
        self._emit_times = [t for t in self._emit_times if seg.last_active_end_ms - t < _RATE_WINDOW_MS]
        if len(self._emit_times) >= self.config.max_segments_per_minute:
            self._stats.segment_dropped_rate_limit_count += 1
            return None
        self._emit_times.append(seg.last_active_end_ms)

        return PerChannelAudioSegment(
            channel_index=c,
            source_id=f"channel_{c}",
            channel_label=f"channel_{c}",
            start_ms=seg.start_ms,
            end_ms=seg.last_active_end_ms,
            duration_ms=duration,
            sample_rate=int(sample_rate),
            pcm16_mono=bytes(seg.pcm),
            rms=round(avg_rms, 4),
            peak=round(seg.peak, 4),
            dominance=round(avg_dom, 4),
            frame_count=seg.frames,
        )

    # ---- transcription ----

    def _record_adapter_error(self, ek: Optional[str]) -> None:
        self._stats.last_error_kind = ek
        if ek == "timeout":
            self._stats.transcribe_timeout_count += 1
        elif ek == "empty_text":
            self._stats.transcribe_empty_text_count += 1
        elif ek in ("provider_error", "exception", "invalid_audio"):
            self._stats.transcribe_provider_error_count += 1
        elif ek == "audio_too_large":
            self._stats.transcribe_audio_too_large_count += 1
        elif ek in ("api_key_missing", "adapter_unavailable", "unknown_provider"):
            self._stats.adapter_unavailable_count += 1
        else:
            self._stats.transcribe_error_count += 1

    def _candidate_from_result(self, result, segment: PerChannelAudioSegment) -> Optional[PerChannelSttCandidate]:
        text = normalize_stt_text(result.text)
        if len(text) < self.config.min_text_chars:
            return None  # текст слишком короткий — кандидат не эмитим
        stt_conf = float(result.confidence) if result.confidence is not None else 0.7
        val = 0.45 * segment.dominance + 0.25 * min(1.0, segment.rms * 4.0) + 0.30 * stt_conf
        attribution_confidence = round(min(0.85, max(0.0, val)), 4)
        source_is_isolated = segment.dominance >= max(self.config.min_dominance, 0.65)
        return PerChannelSttCandidate(
            text=text,
            text_hash=result.text_hash or hash_text(text),
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            audio_source_id=segment.source_id,      # channel_{index} — техническая зона
            channel_label=segment.channel_label,
            source_is_isolated=source_is_isolated,
            attribution_confidence=attribution_confidence,
            channel_index=segment.channel_index,
        )

    async def transcribe_segment(self, segment: PerChannelAudioSegment) -> Optional[PerChannelSttCandidate]:
        """Транскрибировать сегмент через provider-адаптер (bounded: duration/cache/budget/timeout).

        raw audio/text не логируются. None, если адаптер недоступен/ошибка/текст короткий/бюджет.
        """
        self._stats.transcribe_attempt_count += 1
        cfg = self.config

        # 1) длительность аудио в пределах лимита
        if segment.duration_ms > cfg.max_audio_seconds * 1000.0:
            self._stats.transcribe_audio_too_long_count += 1
            self._stats.last_error_kind = "audio_too_long"
            return None

        # 2) cache (hit не тратит бюджет provider-вызовов)
        cache_key = None
        if cfg.cache_enabled and self._cache.max_entries > 0:
            cache_key = hash_audio_for_cache(
                segment.pcm16_mono, segment.sample_rate, cfg.provider, cfg.model_id or "",
                cfg.language_code or "")
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._stats.transcribe_cache_hit_count += 1
                return self._candidate_from_result(cached, segment)
            self._stats.transcribe_cache_miss_count += 1

        # 3) budget — только перед РЕАЛЬНЫМ provider-вызовом. noop не делает внешних вызовов,
        # поэтому бюджет provider-вызовов для него не тратится (default-путь не «съедает» budget).
        is_noop_adapter = getattr(self.adapter, "is_noop", False)
        if not is_noop_adapter:
            if not self._budget.allow(segment.duration_ms):
                self._stats.transcribe_budget_exhausted_count += 1
                self._stats.last_error_kind = "budget_exhausted"
                return None
            self._budget.consume(segment.duration_ms)

        # 4) provider call
        try:
            result = await self.adapter.transcribe_segment(segment, cfg)
        except Exception:  # noqa: BLE001 — provider-ошибка не ломает поток (raw не логируем)
            self._stats.transcribe_provider_error_count += 1
            self._stats.last_error_kind = "exception"
            return None

        if result is None:
            self._stats.adapter_unavailable_count += 1
            self._stats.last_error_kind = "adapter_unavailable"
            return None
        if result.error_kind:
            self._record_adapter_error(result.error_kind)
            return None

        # success
        self._stats.transcribe_success_count += 1
        if result.latency_ms is not None:
            self._latencies.append(float(result.latency_ms))
        if cache_key is not None:
            self._cache.set(cache_key, result)
        return self._candidate_from_result(result, segment)

    def segment_to_source_candidate_payload(self, candidate: PerChannelSttCandidate) -> dict:
        """Payload для SourceAttributionReconciler (совместим с multi_channel candidate-контрактом)."""
        return {
            "text": candidate.text,
            "start_ms": candidate.start_ms,
            "end_ms": candidate.end_ms,
            "audio_source_id": candidate.audio_source_id,   # channel_{index} — техническая зона
            "channel_label": candidate.channel_label,
            "source_is_isolated": candidate.source_is_isolated,
            "source_kind": "multi_channel",
            "attribution_source": "multi_source_segment",
            "attribution_confidence": candidate.attribution_confidence,
            "candidate_pipeline": "per_channel_stt",         # → reconciler.source
        }

    # ---- candidate outcome + stats ----

    def mark_candidate_emitted(self) -> None:
        self._stats.candidate_emit_count += 1

    def mark_candidate_suppressed(self) -> None:
        self._stats.candidate_shadow_suppressed_count += 1

    def get_stats(self) -> PerChannelSttStats:
        s = self._stats
        s.enabled = self.config.enabled
        s.shadow_mode = self.config.shadow_mode
        s.provider = self.config.provider
        s.provider_calls_used = self._budget.calls_used
        s.provider_audio_seconds_used = round(self._budget.audio_seconds_used, 2)
        s.active_channel_count = len(self._active_channels)
        s.average_dominance = (round(sum(self._dom_values) / len(self._dom_values), 4)
                               if self._dom_values else None)
        s.average_transcribe_latency_ms = (round(sum(self._latencies) / len(self._latencies), 1)
                                           if self._latencies else None)
        return s
