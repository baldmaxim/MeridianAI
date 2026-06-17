"""Meeting session, transcription segment, and saved transcription models."""

from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, Integer, Float, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class MeetingSession(Base):
    __tablename__ = "meeting_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Автор встречи — информативная метка, не ключ доступа (общая хронология).
    # SET NULL: встреча переживает удаление пользователя.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
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

    # Этап 1 MVP: справочники + статус/мета (все nullable, обратная совместимость)
    customer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="SET NULL")
    )
    object_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("project_objects.id", ondelete="SET NULL")
    )
    # created_by_user_id дублирует user_id (legacy-владелец) для явной совместимости;
    # новый код пишет оба, бэкфилл миграцией = user_id
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str | None] = mapped_column(String(30), default="active")
    micro_summary: Mapped[str | None] = mapped_column(Text)
    tags_json: Mapped[str | None] = mapped_column(Text)

    # Batch finalization
    audio_path: Mapped[str | None] = mapped_column(String(500))
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    finalization_error: Mapped[str | None] = mapped_column(Text)
    live_segment_count: Mapped[int | None] = mapped_column(Integer)
    final_segment_count: Mapped[int | None] = mapped_column(Integer)

    # Этап 5: финализация встречи (LLM-протокол)
    # not_started | queued | running | completed | partial | error
    finalization_status: Mapped[str] = mapped_column(String(20), default="not_started")
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime)
    protocol_markdown: Mapped[str | None] = mapped_column(Text)
    protocol_json: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text)

    # Этап 7: auto-learning кандидатов для базы знаний
    # not_started | queued | running | completed | error
    learning_status: Mapped[str] = mapped_column(String(20), default="not_started")
    learning_error: Mapped[str | None] = mapped_column(Text)

    # Этап 9: AI-настройки встречи (профиль + замороженный снапшот на время live)
    ai_settings_profile_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ai_settings_profiles.id", ondelete="SET NULL")
    )
    ai_settings_snapshot_json: Mapped[str | None] = mapped_column(Text)


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

    # Этап 6: структурированные подсказки (старые поля выше сохранены для совместимости)
    title: Mapped[str | None] = mapped_column(String(255))
    why: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    card_json: Mapped[str | None] = mapped_column(Text)
    needs_user_check: Mapped[bool] = mapped_column(Boolean, default=False)
    source_mode: Mapped[str | None] = mapped_column(String(20))  # auto|manual|strengthen|fallback
    priority: Mapped[int | None] = mapped_column(Integer)


class MeetingDocumentRecord(Base):
    """Документ, прикреплённый к встрече.

    Legacy-путь (Этапы ≤3): inline content (multipart). Новый путь (Этап 4): связь по
    document_id с таблицей documents (S3 + чанки). Legacy-строки имеют document_id=NULL.
    """
    __tablename__ = "meeting_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str | None] = mapped_column(String(255))
    doc_type: Mapped[str | None] = mapped_column(String(50))
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str | None] = mapped_column(Text)  # legacy inline-текст; для S3-flow NULL
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Этап 4: новый S3-flow
    document_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE")
    )
    added_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)
    included: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        # NULL document_id у legacy-строк не конфликтует (NULL'ы различны в Postgres/SQLite)
        UniqueConstraint("session_id", "document_id", name="uq_meeting_document"),
        Index("ix_meeting_documents_document", "document_id"),
    )


class SavedTranscription(Base):
    __tablename__ = "saved_transcriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE")
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)  # txt | json
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    segment_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
