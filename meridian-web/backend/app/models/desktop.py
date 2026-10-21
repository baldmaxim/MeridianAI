# -*- coding: utf-8 -*-
"""Десктоп-приложение записи встреч.

Приложение на ПК пишет встречу локально (микрофон = «мы», звук системы = «оппонент»),
распознаёт её на месте и при появлении сети отправляет на сервер. Запросы можно повторять
сколько угодно раз — обрыв сети посреди загрузки не должен ни терять, ни дублировать данные.

DesktopDevice — установка приложения. В базе только sha256 токена (как у OCR-агентов):
токен — 256 бит случайности, перебором его не восстановить, а индекс по хэшу даёт поиск без
перебора всех устройств. Отзыв устройства закрывает токен, но не трогает уже принятые встречи.

DesktopMeetingLink — связь «идентификатор встречи на ПК → встреча на сервере». UNIQUE
(user_id, client_uuid) делает создание встречи идемпотентным: повтор вернёт ту же встречу.
device_id при удалении устройства обнуляется — встреча от этого не пропадает.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class DesktopDevice(Base):
    __tablename__ = "desktop_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(20))
    app_version: Mapped[str | None] = mapped_column(String(40))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_desktop_devices_user_id", "user_id"),
    )


class DesktopMeetingLink(Base):
    __tablename__ = "desktop_meeting_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("desktop_devices.id", ondelete="SET NULL")
    )
    client_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meeting_sessions.id", ondelete="CASCADE"), nullable=False
    )
    # online | in_person
    capture_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "client_uuid", name="uq_desktop_meeting_link_client"),
        Index("ix_desktop_meeting_links_meeting_id", "meeting_id"),
    )
