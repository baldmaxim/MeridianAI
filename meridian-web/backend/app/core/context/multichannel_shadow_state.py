"""Multichannel shadow ingest state (Этап 16).

Принимает MAUD2 v2 frames, считает БЕЗОПАСНЫЕ агрегаты (счётчики кадров, каналы, sample rate,
rms/peak/clipping по каналам) и НЕ хранит raw audio, НЕ кормит STT, НЕ создаёт attribution и НЕ
выводит сторону. Только диагностика.
"""

from typing import Optional

from pydantic import BaseModel, Field

from .audio_frame_v2 import is_audio_frame_v2, parse_audio_frame_v2

_HISTORY_CAP = 256


def _median(xs: list) -> Optional[float]:
    if not xs:
        return None
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    return round(ys[mid] if n % 2 else (ys[mid - 1] + ys[mid]) / 2.0, 4)


class AudioMultichannelShadowStats(BaseModel):
    enabled: bool = False
    frame_count: int = 0
    dropped_frame_count: int = 0
    parse_error_count: int = 0
    last_sequence: Optional[int] = None
    sequence_gap_count: int = 0
    max_channels_seen: int = 0
    last_channels: Optional[int] = None
    last_sample_rate: Optional[int] = None
    route_counts: dict = Field(default_factory=dict)
    pipeline_counts: dict = Field(default_factory=dict)
    rms_p50_by_channel: Optional[list] = None
    peak_max_by_channel: Optional[list] = None
    clipping_event_count: int = 0
    last_frame_duration_ms: Optional[float] = None


class AudioMultichannelShadowIngest:
    """Аккумулятор безопасных агрегатов по v2 shadow frames. Raw payload не удерживается."""

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.frame_count = 0
        self.dropped_frame_count = 0
        self.parse_error_count = 0
        self.last_sequence: Optional[int] = None
        self.sequence_gap_count = 0
        self.max_channels_seen = 0
        self.last_channels: Optional[int] = None
        self.last_sample_rate: Optional[int] = None
        self.route_counts: dict = {}
        self.pipeline_counts: dict = {}
        self.clipping_event_count = 0
        self.last_frame_duration_ms: Optional[float] = None
        self._rms_history: list = []   # per-channel rolling rms
        self._peak_max: list = []      # per-channel running max peak

    def note_dropped(self) -> None:
        """Кадр получен, но не принят (accept disabled / backpressure)."""
        self.dropped_frame_count += 1

    def ingest_frame(self, data: bytes) -> bool:
        """Распарсить v2 frame и обновить агрегаты. True если принят, False при parse error.

        Raw payload используется ТОЛЬКО локально для расчёта rms/peak и сразу отбрасывается.
        """
        if not is_audio_frame_v2(data):
            self.parse_error_count += 1
            return False
        try:
            parsed = parse_audio_frame_v2(data)
        except Exception:  # noqa: BLE001 — любой невалидный кадр = parse error, не ломаем поток
            self.parse_error_count += 1
            return False

        h = parsed.header
        self.frame_count += 1
        if self.last_sequence is not None and h.sequence > self.last_sequence + 1:
            self.sequence_gap_count += (h.sequence - self.last_sequence - 1)
        self.last_sequence = h.sequence
        self.last_channels = h.channels
        self.last_sample_rate = h.sample_rate
        self.max_channels_seen = max(self.max_channels_seen, h.channels)
        self.route_counts[h.route] = self.route_counts.get(h.route, 0) + 1
        self.pipeline_counts[h.capture_pipeline] = self.pipeline_counts.get(h.capture_pipeline, 0) + 1
        self.last_frame_duration_ms = parsed.duration_ms_estimate

        for c in range(h.channels):
            while len(self._rms_history) <= c:
                self._rms_history.append([])
            hist = self._rms_history[c]
            hist.append(parsed.rms_by_channel[c] if c < len(parsed.rms_by_channel) else 0.0)
            if len(hist) > _HISTORY_CAP:
                hist.pop(0)
            while len(self._peak_max) <= c:
                self._peak_max.append(0.0)
            pk = parsed.peak_by_channel[c] if c < len(parsed.peak_by_channel) else 0.0
            if pk > self._peak_max[c]:
                self._peak_max[c] = pk
        if any(parsed.clipping_by_channel):
            self.clipping_event_count += 1
        # parsed (и payload) выходит из области видимости здесь — raw audio не сохраняется
        return True

    def get_stats(self, *, enabled: bool = False) -> AudioMultichannelShadowStats:
        rms_p50 = [_median(h) for h in self._rms_history] if self._rms_history else None
        peak_max = list(self._peak_max) if self._peak_max else None
        return AudioMultichannelShadowStats(
            enabled=enabled,
            frame_count=self.frame_count,
            dropped_frame_count=self.dropped_frame_count,
            parse_error_count=self.parse_error_count,
            last_sequence=self.last_sequence,
            sequence_gap_count=self.sequence_gap_count,
            max_channels_seen=self.max_channels_seen,
            last_channels=self.last_channels,
            last_sample_rate=self.last_sample_rate,
            route_counts=dict(self.route_counts),
            pipeline_counts=dict(self.pipeline_counts),
            rms_p50_by_channel=rms_p50,
            peak_max_by_channel=peak_max,
            clipping_event_count=self.clipping_event_count,
            last_frame_duration_ms=self.last_frame_duration_ms,
        )
