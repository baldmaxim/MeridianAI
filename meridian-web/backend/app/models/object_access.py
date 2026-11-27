"""Ручной доступ к проектам: гранты по объекту/заказчику и заявки на доступ."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class UserObjectAccess(Base):
    """Грант: пользователь видит объект (и его встречи/документы)."""

    __tablename__ = "user_object_access"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    object_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project_objects.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserCustomerAccess(Base):
    """Грант: пользователь видит все объекты заказчика (включая будущие)."""

    __tablename__ = "user_customer_access"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ObjectAccessRequest(Base):
    """Заявка на доступ к объекту: pending → approved | rejected."""

    __tablename__ = "object_access_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    object_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project_objects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index(
            "uq_object_access_requests_pending",
            "user_id",
            "object_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_object_access_requests_status", "status"),
    )
