"""Batch transcription job model."""

from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class BatchJob(Base):
    """Batch audio transcription and protocol generation job."""
    __tablename__ = "batch_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    # uploaded | compressing | transcribing | generating_protocol | done | error

    # Задача 5: офлайн-дозапись. kind='gap_fill' + meeting_id → влить сегменты в встречу.
    kind: Mapped[str | None] = mapped_column(String(20))  # None — обычный батч; gap_fill — дыра записи
    meeting_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="SET NULL"), index=True, nullable=True
    )

    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_size: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)

    compressed_path: Mapped[str | None] = mapped_column(String(500))
    compressed_size: Mapped[int | None] = mapped_column(Integer)

    transcription_text: Mapped[str | None] = mapped_column(Text)
    transcription_json: Mapped[str | None] = mapped_column(Text)

    protocol_markdown: Mapped[str | None] = mapped_column(Text)
    protocol_json: Mapped[str | None] = mapped_column(Text)

    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
