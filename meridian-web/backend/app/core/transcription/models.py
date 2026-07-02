"""Data models for transcription."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List
from uuid import uuid4


# ---------------------------------------------------------------------------
# Legacy model (Deepgram / Gemini backward compat)
# ---------------------------------------------------------------------------

@dataclass
class TranscriptSegment:
    """Single transcription segment (legacy, used by Deepgram/Gemini)."""
    speaker: str
    text: str
    start_time: float
    end_time: float
    timestamp: datetime
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# ElevenLabs production models
# ---------------------------------------------------------------------------

UNKNOWN_SPEAKER = "unknown_speaker"


class WordType(str, Enum):
    WORD = "word"
    SPACING = "spacing"
    PUNCTUATION = "punctuation"


class SegmentOrigin(str, Enum):
    LIVE_COMMITTED = "live_committed"
    BATCH_FINALIZED = "batch_finalized"


@dataclass(frozen=True)
class TranscriptWord:
    """Single word from committed_transcript_with_timestamps.

    Immutable — words are facts from the STT engine, never modified.
    """
    text: str
    start: float
    end: float
    type: WordType = WordType.WORD
    logprob: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "type": self.type.value,
            "logprob": self.logprob,
        }


@dataclass
class CommittedSegment:
    """Committed (final) transcription segment — unit of truth.

    Contains full word array for evidence spans and batch reconciliation.
    NEVER created from partial_transcript events.
    """
    segment_id: str = field(default_factory=lambda: uuid4().hex[:12])
    text: str = ""
    words: List[TranscriptWord] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    wall_clock: datetime = field(default_factory=datetime.now)
    speaker_id: str = UNKNOWN_SPEAKER
    speaker_label: Optional[str] = None
    origin: SegmentOrigin = SegmentOrigin.LIVE_COMMITTED
    avg_logprob: Optional[float] = None
    min_logprob: Optional[float] = None
    word_count: int = 0
    # Этап 9.8: абсолютные server-эпохи РЕЧИ (не момента прихода committed-события).
    # Считаются как primary_stream_start_server_ms + provider-relative start/end.
    # None, если якорь старта стрима неизвестен (graceful — падаем на wall_clock/server_ts_ms).
    speech_start_ms: Optional[int] = None
    speech_end_ms: Optional[int] = None
    # Этап 8: optional structured source attribution (зона записи: source/channel/isolated).
    # Заполняется только pipeline'ом, который реально знает изолированный per-speaker источник.
    # НЕ сторона и НЕ личность. None по умолчанию → старое поведение/сериализация не меняются.
    source_attribution: Optional[dict] = None

    def __post_init__(self):
        if self.words:
            if not self.text:
                self.text = "".join(w.text for w in self.words).strip()
            self.start_time = self.words[0].start
            self.end_time = self.words[-1].end
            self.word_count = sum(1 for w in self.words if w.type == WordType.WORD)
            logprobs = [w.logprob for w in self.words if w.logprob is not None]
            if logprobs:
                self.avg_logprob = sum(logprobs) / len(logprobs)
                self.min_logprob = min(logprobs)

    @property
    def is_low_confidence(self) -> bool:
        return self.min_logprob is not None and self.min_logprob < -1.0

    @property
    def server_ts_ms(self) -> int:
        """Абсолютный server timeline (epoch ms) — основа для channel alignment (Этап 9.1)."""
        return int(self.wall_clock.timestamp() * 1000)

    def assign_speech_timestamps(self, stream_start_server_ms: Optional[int]) -> None:
        """Этап 9.8: проставить абсолютные server-эпохи речи по якорю старта стрима.

        provider-relative start/end (секунды) + якорь → epoch ms. Без якоря — оставляем None.
        Не меняет байты/протокол STT; чисто производная метка для атрибуции эпох.
        """
        if stream_start_server_ms is None:
            return
        self.speech_start_ms = stream_start_server_ms + int(round(self.start_time * 1000))
        self.speech_end_ms = stream_start_server_ms + int(round(self.end_time * 1000))

    @property
    def effective_speech_start_ms(self) -> int:
        """Speech-start если известен, иначе fallback на server_ts_ms (момент прихода)."""
        return self.speech_start_ms if self.speech_start_ms is not None else self.server_ts_ms

    @property
    def effective_speech_end_ms(self) -> int:
        return self.speech_end_ms if self.speech_end_ms is not None else self.server_ts_ms

    def to_wire(self) -> dict:
        """Minimal payload for WS client (backward-compat with transcript type)."""
        return {
            "segment_id": self.segment_id,
            "segment_key": self.segment_id,
            "speaker": self.speaker_label or self.speaker_id,
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "timestamp": self.wall_clock.strftime("%H:%M:%S"),
            "server_ts_ms": self.server_ts_ms,
            "is_partial": False,
            "confidence": self.avg_logprob,
        }

    def to_wire_full(self) -> dict:
        """Full payload with word-level data for committed_transcript type."""
        return {
            "segment_id": self.segment_id,
            "segment_key": self.segment_id,
            "speaker": self.speaker_label or self.speaker_id,
            "text": self.text,
            "words": [w.to_dict() for w in self.words],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "confidence": self.avg_logprob,
            "timestamp": self.wall_clock.strftime("%H:%M:%S"),
            "server_ts_ms": self.server_ts_ms,
            "speech_start_ms": self.speech_start_ms,
            "speech_end_ms": self.speech_end_ms,
        }

    def to_dict(self) -> dict:
        """Full payload for persistence."""
        return {
            "segment_id": self.segment_id,
            "text": self.text,
            "words": [w.to_dict() for w in self.words],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "wall_clock": self.wall_clock.isoformat(),
            "speaker_id": self.speaker_id,
            "speaker_label": self.speaker_label,
            "origin": self.origin.value,
            "word_count": self.word_count,
            "avg_logprob": self.avg_logprob,
            "min_logprob": self.min_logprob,
        }

    def to_legacy(self) -> TranscriptSegment:
        """Convert to legacy TranscriptSegment for backward compat."""
        return TranscriptSegment(
            speaker=self.speaker_label or self.speaker_id,
            text=self.text,
            start_time=self.start_time,
            end_time=self.end_time,
            timestamp=self.wall_clock,
            confidence=self.avg_logprob,
        )


@dataclass
class PartialTranscript:
    """Ephemeral partial transcript — UI preview only.

    NEVER stored. NEVER used for AI analysis. NEVER persisted.
    """
    text: str
    received_at: datetime = field(default_factory=datetime.now)

    def to_wire(self) -> dict:
        return {
            "speaker": "...",
            "text": self.text,
            "timestamp": self.received_at.strftime("%H:%M:%S"),
            "is_partial": True,
        }
