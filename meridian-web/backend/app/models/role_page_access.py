"""RolePageAccess model — доступ к страницам по роли (одна строка на роль)."""

from datetime import datetime

from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class RolePageAccess(Base):
    __tablename__ = "role_page_access"

    id: Mapped[int] = mapped_column(primary_key=True)
    role_name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    # JSON-массив ключей страниц, например ["objects","batch"].
    allowed_pages: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
