"""Структурированные итоги встречи (Этап 5): решения, задачи, риски, открытые вопросы.

Дублируют protocol_json для удобной фильтрации/выборки встреч по задачам/рискам.
evidence_json — список ссылок-доказательств [{timecode, speaker, quote}].
"""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class MeetingDecision(Base):
    __tablename__ = "meeting_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # accepted | preliminary | rejected | postponed | unclear
    status: Mapped[str] = mapped_column(String(20), default="unclear")
    evidence_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_meeting_decisions_meeting", "meeting_id"),
        Index("ix_meeting_decisions_status", "status"),
    )


class MeetingActionItem(Base):
    __tablename__ = "meeting_action_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE")
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    owner_text: Mapped[str | None] = mapped_column(String(255))
    due_text: Mapped[str | None] = mapped_column(String(255))
    # open | done | cancelled
    status: Mapped[str] = mapped_column(String(20), default="open")
    evidence_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_meeting_action_items_meeting", "meeting_id"),
        Index("ix_meeting_action_items_status", "status"),
    )


class MeetingRisk(Base):
    __tablename__ = "meeting_risks"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # low | medium | high
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    evidence_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_meeting_risks_meeting", "meeting_id"),
        Index("ix_meeting_risks_severity", "severity"),
    )


class MeetingOpenQuestion(Base):
    __tablename__ = "meeting_open_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_meeting_open_questions_meeting", "meeting_id"),
    )
