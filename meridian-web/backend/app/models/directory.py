"""Справочники (заказчики, объекты, отделы) и базовая модель доступа сотрудников.

Этап 1 MVP. Scope — общий для фирмы (пока одна фирма). Колонка ``owner_user_id``
хранит создателя и служит seam'ом под будущий ``organization_id`` (см. CLAUDE.md).
Контроль доступа применяется на уровне объектов и встреч (см. app/services/access.py).
"""

from datetime import datetime

from sqlalchemy import (
    String,
    Text,
    Boolean,
    DateTime,
    Integer,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Customer(Base):
    """Заказчик. Создаётся вручную в справочнике."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    # owner_user_id — создатель (метка автора); seam под будущий organization_id.
    # SET NULL: заказчик переживает удаление пользователя.
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    inn: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_customers_owner_name", "owner_user_id", "name"),
    )


class ProjectObject(Base):
    """Объект (стройка/проект). Привязан к заказчику."""

    __tablename__ = "project_objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    # owner_user_id — метка автора. SET NULL: объект переживает удаление пользователя.
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_project_objects_customer", "customer_id"),
    )


class MeetingParticipant(Base):
    """Участник встречи (many-to-many meeting_sessions <-> users)."""

    __tablename__ = "meeting_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20), default="participant")  # owner | participant | viewer
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_meeting_participant"),
        Index("ix_meeting_participants_user", "user_id"),
        Index("ix_meeting_participants_meeting", "meeting_id"),
    )
