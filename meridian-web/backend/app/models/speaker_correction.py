"""Segment-level коррекции диаризации (Этап 8).

Overlay поверх raw STT: одна реплика (segment) может относиться к другой стороне,
чем speaker label в целом. Raw transcript НЕ перезаписывается — это отдельный слой
поправок, который применяется при сборке дерева общения и prompt-facing представления.

Правило определения стороны реплики (по убыванию приоритета):
  1) segment-level side correction;
  2) corrected_speaker_label → speaker role map;
  3) original_speaker_label → speaker role map;
  4) unknown.
"""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class MeetingSpeakerSegmentCorrection(Base):
    __tablename__ = "meeting_speaker_segment_corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), nullable=False
    )
    # стабильный ключ реплики (= TranscriptSegmentRecord.segment_id)
    segment_key: Mapped[str] = mapped_column(String(200), nullable=False)
    original_speaker_label: Mapped[str | None] = mapped_column(String(120))
    corrected_speaker_label: Mapped[str | None] = mapped_column(String(120))
    # только self | opponent | NULL (две публичные стороны)
    side: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("meeting_id", "segment_key", name="uq_meeting_speaker_segment_correction"),
        Index("ix_speaker_seg_corr_meeting", "meeting_id"),
        Index("ix_speaker_seg_corr_segment", "segment_key"),
        Index("ix_speaker_seg_corr_corrected_label", "corrected_speaker_label"),
        Index("ix_speaker_seg_corr_side", "side"),
    )
