"""File record model (§15): связь объекта S3 с пользователем, soft delete."""

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class FileRecord(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    size: Mapped[int | None] = mapped_column(Integer)
    mime: Mapped[str | None] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)  # document | batch_audio | meeting_audio | stash
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|active|deleted
    # Задача 3: привязка архива живого аудио к встрече (NULL — не привязано). ON DELETE SET NULL.
    meeting_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # Мини-облако (purpose="stash"): срок авто-удаления. NULL для остальных назначений.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
