"""User settings model."""

from datetime import datetime

from sqlalchemy import String, Float, Boolean, DateTime, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    stt_provider: Mapped[str] = mapped_column(String(20), default="deepgram")
    llm_model: Mapped[str] = mapped_column(
        String(100), default="google/gemini-3-flash-preview"
    )
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    user_role: Mapped[str] = mapped_column(String(50), default="gen_contractor")
    use_streaming: Mapped[bool] = mapped_column(Boolean, default=True)
    diarization: Mapped[bool] = mapped_column(Boolean, default=True)
    diarization_max_speakers: Mapped[int] = mapped_column(
        Integer, server_default="3", default=3
    )
    silence_filter: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_suggestion_types: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    custom_trigger_keywords: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    local_storage_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
