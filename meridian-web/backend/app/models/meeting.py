"""Meeting session, transcription segment, and saved transcription models."""

from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class MeetingSession(Base):
    __tablename__ = "meeting_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE")
    )
    title: Mapped[str | None] = mapped_column(String(255))
    meeting_topic: Mapped[str | None] = mapped_column(Text)
    meeting_notes: Mapped[str | None] = mapped_column(Text)
    negotiation_type: Mapped[str | None] = mapped_column(String(50))
    meeting_role: Mapped[str | None] = mapped_column(String(255))
    opponent_weaknesses: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Batch finalization
    audio_path: Mapped[str | None] = mapped_column(String(500))
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    finalization_error: Mapped[str | None] = mapped_column(Text)
    live_segment_count: Mapped[int | None] = mapped_column(Integer)
    final_segment_count: Mapped[int | None] = mapped_column(Integer)


class TranscriptSegmentRecord(Base):
    """Persisted transcript segment. Written on session end or periodic flush."""
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), index=True
    )
    segment_id: Mapped[str] = mapped_column(String(12), unique=True)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    wall_clock: Mapped[datetime] = mapped_column(DateTime)

    speaker_id: Mapped[str] = mapped_column(String(50), default="unknown_speaker")
    speaker_label: Mapped[str | None] = mapped_column(String(100))

    origin: Mapped[str] = mapped_column(String(20))  # SegmentOrigin.value

    word_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_logprob: Mapped[float | None] = mapped_column(Float)
    min_logprob: Mapped[float | None] = mapped_column(Float)

    # Words stored as JSON blob — queried only for export/evidence
    words_json: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MeetingSuggestion(Base):
    """Persisted AI suggestion or strengthen-position response."""
    __tablename__ = "meeting_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_auto: Mapped[bool] = mapped_column(Boolean, default=False)
    suggestion_type: Mapped[str | None] = mapped_column(String(20))  # priority/counter/question/risk
    trigger: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[int | None] = mapped_column(Integer)
    context_info: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="suggestion")  # suggestion | strengthen
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MeetingDocumentRecord(Base):
    """Document attached to a meeting session."""
    __tablename__ = "meeting_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SavedTranscription(Base):
    __tablename__ = "saved_transcriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)  # txt | json
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    segment_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
