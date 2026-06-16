"""Дерево общения встречи (Conversation Tree).

Структурированная карта переговоров по темам: для каждой темы фиксируется позиция
нашей стороны и оппонента, последние реплики и ссылки на сегменты транскрипта.
Строится детерминированно по committed-сегментам; LLM-уточнение — по запросу.
"""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


# допустимые статусы темы
TOPIC_STATUSES = ("new", "updated", "resolved", "disputed", "needs_follow_up")
# статусы, выставленные вручную и «липкие» — авто-апдейт их не перезатирает
STICKY_STATUSES = ("resolved", "disputed", "needs_follow_up")


class MeetingConversationTopic(Base):
    __tablename__ = "meeting_conversation_topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")

    our_summary: Mapped[str | None] = mapped_column(Text)
    opponent_summary: Mapped[str | None] = mapped_column(Text)
    our_last_text: Mapped[str | None] = mapped_column(Text)
    opponent_last_text: Mapped[str | None] = mapped_column(Text)

    # JSON-массивы [{segment_id, speaker, timecode, text}], ограничены последними N
    our_refs_json: Mapped[str | None] = mapped_column(Text)
    opponent_refs_json: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[str | None] = mapped_column(Text)

    last_updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("meeting_id", "normalized_key", name="uq_conv_topic_meeting_key"),
        Index("ix_conv_topics_meeting", "meeting_id"),
        Index("ix_conv_topics_key", "normalized_key"),
        Index("ix_conv_topics_status", "status"),
        Index("ix_conv_topics_last_updated", "last_updated_at"),
    )
