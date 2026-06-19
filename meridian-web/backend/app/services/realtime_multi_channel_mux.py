"""Realtime multi-channel mux (Этап 9.6).

Читает canonical frames выбранных tracks по общей frame_index timeline, заполняет
отсутствующие кадры тишиной, interleave-ит в raw PCM16 multichannel и отдаёт чанками
с real-time pacing. Без resampling/normalization/drift-correction/offsets. Ingest не мутируется.
"""

import time
from dataclasses import dataclass, field
from typing import Literal

from .multi_channel_wav import interleave_pcm16_channels

MuxSessionStatus = Literal[
    "idle", "buffering", "ready", "streaming", "degraded", "stopping", "stopped", "failed",
]


class RealtimeMuxError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class RealtimeMuxChannel:
    channel_index: int
    track_id: str
    connection_id: str
    generation: int
    source_kind: str
    label: str
    side: str | None


@dataclass(frozen=True)
class RealtimeMuxChunk:
    first_frame_index: int
    last_frame_index: int
    start_server_ms: int
    end_server_ms: int
    frame_count: int
    channel_count: int
    pcm16_interleaved: bytes
    missing_frames_by_channel: tuple   # tuple[int, ...]


@dataclass
class RealtimeMuxDiagnostics:
    chunks_emitted: int = 0
    frames_emitted: int = 0
    bytes_emitted: int = 0
    missing_frames_by_channel: list = field(default_factory=list)
    total_frames_by_channel: list = field(default_factory=list)
    send_queue_depth: int = 0
    max_send_queue_depth: int = 0
    first_frame_index: int | None = None
    last_frame_index: int | None = None
    started_server_ms: int | None = None
    last_emit_server_ms: int | None = None
    pacing_lag_ms: float = 0.0
    provider_send_latency_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None


# --- pure helpers ---

def pcm16_silence_frame(sample_rate: int, frame_ms: int) -> bytes:
    samples = int(round(sample_rate * frame_ms / 1000.0))
    return b"\x00" * (samples * 2)


def interleave_pcm16_frames(channel_frames: list, *, expected_mono_bytes: int) -> bytes:
    """Interleave одного frame_index по каналам. Каждый mono-кадр строго canonical size."""
    for f in channel_frames:
        if len(f) != expected_mono_bytes:
            raise RealtimeMuxError("MUX_MALFORMED_FRAME",
                                   "Кадр канала не канонического размера")
    return interleave_pcm16_channels(channel_frames)


# --- muxer ---

class RealtimeMultiChannelMuxer:
    def __init__(self, *, ingest, channels: tuple, sample_rate: int, frame_ms: int,
                 playout_delay_ms: int, send_chunk_ms: int) -> None:
        self.ingest = ingest
        self.channels = channels
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.playout_delay_ms = playout_delay_ms
        self.send_chunk_ms = send_chunk_ms
        self.track_ids = [c.track_id for c in channels]
        self.channel_count = len(channels)
        self.frames_per_chunk = max(1, send_chunk_ms // frame_ms)
        self.frame_bytes = int(round(sample_rate * frame_ms / 1000.0)) * 2
        self._silence = pcm16_silence_frame(sample_rate, frame_ms)
        self._silence_counts = [0] * self.channel_count
        self._total_counts = [0] * self.channel_count
        self._consec_silence = [0] * self.channel_count   # хвостовой прогон тишины (windowed)

    def choose_start_index(self, *, now_server_ms: int, min_prebuffer_ms: int) -> int:
        lo, hi = self.ingest.get_common_range(self.track_ids)
        if lo is None or hi is None:
            raise RealtimeMuxError("MUX_BUFFERING", "Нет общего окна каналов", retryable=True)
        prebuffer_frames = max(1, min_prebuffer_ms // self.frame_ms)
        if (hi - lo + 1) < prebuffer_frames:
            raise RealtimeMuxError("MUX_BUFFERING", "Недостаточно prebuffer", retryable=True)
        # старт ≈ (now - playout) на сетке, но не позднее (hi - prebuffer + 1), не старше lo
        start_target = (now_server_ms - self.playout_delay_ms) // self.frame_ms
        max_start = hi - prebuffer_frames + 1
        return min(max(start_target, lo), max_start)

    def build_chunk(self, *, first_frame_index: int) -> RealtimeMuxChunk:
        missing = [0] * self.channel_count
        parts: list[bytes] = []
        for k in range(self.frames_per_chunk):
            idx = first_frame_index + k
            read = self.ingest.read_tracks_at_index(track_ids=self.track_ids, frame_index=idx)
            frame_channels: list[bytes] = []
            for ci, (_tid, pcm) in enumerate(read.tracks):
                self._total_counts[ci] += 1
                if pcm is not None and len(pcm) == self.frame_bytes:
                    frame_channels.append(pcm)
                    self._consec_silence[ci] = 0
                else:
                    frame_channels.append(self._silence)
                    missing[ci] += 1
                    self._silence_counts[ci] += 1
                    self._consec_silence[ci] += 1
            parts.append(interleave_pcm16_frames(frame_channels, expected_mono_bytes=self.frame_bytes))
        pcm = b"".join(parts)
        last = first_frame_index + self.frames_per_chunk - 1
        return RealtimeMuxChunk(
            first_frame_index=first_frame_index, last_frame_index=last,
            start_server_ms=first_frame_index * self.frame_ms,
            end_server_ms=(last + 1) * self.frame_ms,
            frame_count=self.frames_per_chunk, channel_count=self.channel_count,
            pcm16_interleaved=pcm, missing_frames_by_channel=tuple(missing),
        )

    def channel_silence_ratios(self) -> list:
        return [
            round(self._silence_counts[i] / self._total_counts[i], 4) if self._total_counts[i] else 0.0
            for i in range(self.channel_count)
        ]

    def consecutive_silence_ms(self) -> list:
        """Длительность ХВОСТОВОЙ тишины канала (мс) — windowed-сигнал для watchdog."""
        return [c * self.frame_ms for c in self._consec_silence]


# --- scheduler (real-time pacing) ---

class RealtimeMuxScheduler:
    """Monotonic-пейсинг: чанк N в start_monotonic + N*chunk/1000. Без burst/catch-up/drop."""

    def __init__(self, *, muxer: RealtimeMultiChannelMuxer, start_frame_index: int,
                 send_chunk_ms: int, max_pacing_lag_ms: int = 2000) -> None:
        self.muxer = muxer
        self.start_frame_index = start_frame_index
        self.send_chunk_ms = send_chunk_ms
        self.max_pacing_lag_ms = max_pacing_lag_ms
        self.frames_per_chunk = muxer.frames_per_chunk
        self._start_monotonic: float | None = None
        self._n = 0

    def first_index_for(self, n: int) -> int:
        return self.start_frame_index + n * self.frames_per_chunk

    def target_monotonic(self, n: int) -> float:
        assert self._start_monotonic is not None
        return self._start_monotonic + n * self.send_chunk_ms / 1000.0

    def begin(self) -> None:
        self._start_monotonic = time.monotonic()
        self._n = 0

    def next_chunk_blocking_delay(self) -> float:
        """Сколько спать до следующего чанка (>=0). Проверяет lag → MUX_PACING_OVERRUN."""
        target = self.target_monotonic(self._n)
        now = time.monotonic()
        delay = target - now
        if delay < 0 and (-delay * 1000.0) > self.max_pacing_lag_ms:
            raise RealtimeMuxError("MUX_PACING_OVERRUN", "Pacing отстал больше предела")
        return max(0.0, delay)

    def build_next(self) -> RealtimeMuxChunk:
        chunk = self.muxer.build_chunk(first_frame_index=self.first_index_for(self._n))
        self._n += 1
        return chunk
