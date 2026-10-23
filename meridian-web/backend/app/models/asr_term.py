"""Термины словаря правки распознавания (имена, отраслевые слова)."""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AsrTerm(Base):
    """Термин для правки распознанного текста. owner_user_id NULL — общий для всех."""
    __tablename__ = "asr_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(300), nullable=False)
    # JSON-массив строк: как термин обычно искажается при распознавании
    aliases_json: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="name", server_default="name")  # name|term
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )
