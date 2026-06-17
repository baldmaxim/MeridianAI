"""Источники контекста встречи (Этап 8): выбранные пользователем previous meetings и пр.

Единый слой источников контекста. Для Этапа 8 основной source_type="previous_meeting".
Документы остаются в MeetingDocumentRecord (Этап 4) — здесь не дублируются.
included=true проставляется ТОЛЬКО явным действием пользователя (без авто-выбора).
Уникальность (meeting_id, source_type, source_id) при source_id NOT NULL — partial unique
в миграции; app-level idempotent-проверка в api/services.
"""

from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class MeetingContextSource(Base):
    __tablename__ = "meeting_context_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE")
    )
    # previous_meeting | document | manual | customer_profile | object_profile | rag_folder
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # previous_meeting → meeting_sessions.id; rag_folder → rag_folders.id; manual → NULL
    source_id: Mapped[int | None] = mapped_column(Integer)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    added_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_meeting_context_sources_meeting", "meeting_id"),
        Index("ix_meeting_context_sources_type_source", "source_type", "source_id"),
        Index("ix_meeting_context_sources_included", "included"),
    )
