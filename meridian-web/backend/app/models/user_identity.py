"""External identity link (§12): связь Keycloak-идентичности с локальным пользователем.

Сохраняет роли существующих пользователей при SSO-миграции: маппинг по (provider, subject),
роль из Keycloak применяется ТОЛЬКО при создании нового пользователя.
"""

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class UserIdentity(Base):
    __tablename__ = "user_identities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)  # keycloak
    subject: Mapped[str] = mapped_column(String(255), nullable=False)  # sub из OIDC
    email_at_link: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),)
