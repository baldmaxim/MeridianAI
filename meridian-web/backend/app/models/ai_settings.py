"""Профили AI-настроек (Этап 9): провайдеры, модели, режимы, тогглы и лимиты.

Переносит управление поведением AI из кода/.env в настраиваемые профили.
.env/config остаются ultimate-fallback. Секреты (API keys) здесь НЕ хранятся —
только выбор провайдера/модели/режима. owner_user_id — seam под organization_id.
"""

from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AISettingsProfile(Base):
    __tablename__ = "ai_settings_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # user | meeting | system
    profile_type: Mapped[str] = mapped_column(String(20), default="user")

    # провайдеры/модели (NULL → наследуется из config/.env)
    stt_provider: Mapped[str | None] = mapped_column(String(40))
    stt_model: Mapped[str | None] = mapped_column(String(100))
    llm_provider: Mapped[str | None] = mapped_column(String(40))
    live_suggestion_model: Mapped[str | None] = mapped_column(String(100))
    strengthen_model: Mapped[str | None] = mapped_column(String(100))
    finalization_model: Mapped[str | None] = mapped_column(String(100))
    learning_model: Mapped[str | None] = mapped_column(String(100))

    # fast | balanced | deep
    suggestion_mode: Mapped[str] = mapped_column(String(20), default="balanced")

    # тогглы
    auto_suggestions_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    document_context_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    knowledge_context_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    previous_meetings_context_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    suggestion_structured_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    finalization_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    learning_extraction_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    conversation_tree_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # лимиты
    max_auto_cards: Mapped[int] = mapped_column(Integer, default=2)
    max_manual_cards: Mapped[int] = mapped_column(Integer, default=5)
    auto_suggestion_min_interval_seconds: Mapped[int] = mapped_column(Integer, default=20)
    document_context_max_chunks: Mapped[int | None] = mapped_column(Integer)
    document_context_max_chars: Mapped[int | None] = mapped_column(Integer)
    previous_context_max_meetings: Mapped[int | None] = mapped_column(Integer)
    previous_context_max_chars: Mapped[int | None] = mapped_column(Integer)
    knowledge_context_max_items: Mapped[int | None] = mapped_column(Integer)

    # произвольные расширения (НЕ для секретов)
    settings_json: Mapped[str | None] = mapped_column(Text)

    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_ai_profiles_owner", "owner_user_id"),
        Index("ix_ai_profiles_owner_default", "owner_user_id", "is_default"),
        Index("ix_ai_profiles_type", "profile_type"),
    )
