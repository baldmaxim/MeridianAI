"""Production cutover (Этап 9.8): эпохи транскрипции + сохранённые multi-channel сегменты.

Источник истины авторитетного транскрипта встречи. Эпоха = непрерывный отрезок server
timeline с одним источником ("single" committed STT | "multi_channel" promoted live).
Переключения источника = новые эпохи. Multi-channel сегменты — ТОЛЬКО нормализованный
текст + метаданные стороны/канала/времени; НИКОГДА не raw/PCM/слова-с-аудио.
"""

from datetime import datetime

from sqlalchemy import (
    String, Text, Boolean, DateTime, Integer, BigInteger, Float, ForeignKey,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class TranscriptionEpoch(Base):
    """Отрезок встречи с одним авторитетным источником транскрипта."""

    __tablename__ = "meeting_transcription_epochs"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), nullable=False
    )
    epoch_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based порядок
    # "single" | "multi_channel"
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    start_server_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_server_ms: Mapped[int | None] = mapped_column(BigInteger)  # NULL = открытая (текущая)
    # initial | manual_promote | manual_fallback | auto_fallback_failure | recovery_fallback
    reason: Mapped[str | None] = mapped_column(String(40))
    automatic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    # session_id live multi-channel сессии (для multi-эпох), иначе NULL
    live_session_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("meeting_id", "epoch_index", name="uq_transcription_epoch_meeting_index"),
        Index("ix_transcription_epoch_meeting", "meeting_id"),
    )


class MultiChannelSegmentRecord(Base):
    """Нормализованный final multi-channel сегмент авторитетной эпохи (без raw/PCM)."""

    __tablename__ = "meeting_multi_channel_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), nullable=False
    )
    epoch_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("meeting_transcription_epochs.id", ondelete="CASCADE")
    )
    # стабильный ключ (= live segment_id "mclive:...") — дедуп в пределах встречи
    segment_key: Mapped[str] = mapped_column(String(200), nullable=False)
    session_id: Mapped[str] = mapped_column(String(40), nullable=False)
    channel_index: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_label: Mapped[str | None] = mapped_column(String(120))
    # self | opponent | NULL (две публичные стороны)
    side: Mapped[str | None] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    start_server_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_server_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("meeting_id", "segment_key", name="uq_multi_channel_segment_key"),
        Index("ix_multi_channel_segment_meeting", "meeting_id"),
        Index("ix_multi_channel_segment_epoch", "epoch_id"),
    )
