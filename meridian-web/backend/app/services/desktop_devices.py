# -*- coding: utf-8 -*-
"""Устройства десктоп-приложения: вход, токен, отзыв.

Токен выдаётся один раз при входе, в базе только sha256 (как у OCR-агентов). Все функции
коммит оставляют вызывающему, кроме touch_device — там обновление раз в минуту.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.service import verify_password
from ..models.desktop import DesktopDevice
from ..models.user import User
from .ocr_queue import hash_token

logger = logging.getLogger("meridian.desktop_devices")

# last_seen_at пишем не чаще раза в минуту: приложение шлёт пачки запросов подряд.
LAST_SEEN_THROTTLE = timedelta(seconds=60)


@dataclass
class DesktopAuth:
    device: DesktopDevice
    user: User


def _now() -> datetime:
    return datetime.utcnow()


async def check_credentials(db: AsyncSession, email: str, password: str) -> tuple[User | None, str | None]:
    """(пользователь, None) при успехе, иначе (user|None, причина): no_user | bad_password | inactive.

    Пароль проверяет тот же verify_password, что и веб-вход.
    """
    user = (await db.execute(
        select(User).where(User.email == (email or "").strip().lower())
    )).scalar_one_or_none()
    if user is None:
        return None, "no_user"
    if not verify_password(password, user.password_hash):
        return user, "bad_password"
    if not user.is_active:
        return user, "inactive"
    return user, None


async def enroll_device(
    db: AsyncSession, user_id: int, name: str,
    platform: str | None = None, app_version: str | None = None,
) -> tuple[DesktopDevice, str]:
    """Завести устройство. Токен показывается один раз: в базе только его хэш."""
    token = secrets.token_urlsafe(32)
    device = DesktopDevice(
        user_id=user_id,
        name=(name or "").strip()[:120] or "Компьютер",
        platform=((platform or "").strip()[:20] or None),
        app_version=((app_version or "").strip()[:40] or None),
        token_hash=hash_token(token),
        created_at=_now(),
        last_seen_at=_now(),
    )
    db.add(device)
    await db.flush()
    logger.info("заведено устройство десктоп-приложения %s", device.id)
    return device, token


async def authenticate_device(db: AsyncSession, token: str | None) -> DesktopAuth | None:
    """Устройство и его владелец по токену; None — токен неизвестен, отозван или юзер неактивен."""
    if not token:
        return None
    row = (await db.execute(
        select(DesktopDevice, User)
        .join(User, User.id == DesktopDevice.user_id)
        .where(DesktopDevice.token_hash == hash_token(token), DesktopDevice.revoked_at.is_(None))
    )).first()
    if row is None:
        return None
    device, user = row
    if not user.is_active:
        return None
    return DesktopAuth(device=device, user=user)


async def touch_device(db: AsyncSession, device: DesktopDevice) -> None:
    """Отметить активность и закоммитить; не чаще раза в минуту."""
    now = _now()
    if device.last_seen_at is not None and now - device.last_seen_at < LAST_SEEN_THROTTLE:
        return
    device.last_seen_at = now
    await db.commit()


async def list_devices(db: AsyncSession, user_id: int) -> list[DesktopDevice]:
    return list((await db.execute(
        select(DesktopDevice)
        .where(DesktopDevice.user_id == user_id, DesktopDevice.revoked_at.is_(None))
        .order_by(DesktopDevice.created_at.desc(), DesktopDevice.id.desc())
    )).scalars().all())


async def revoke_device(db: AsyncSession, device: DesktopDevice) -> bool:
    """Закрыть токен. False — устройство уже было отозвано."""
    if device.revoked_at is not None:
        return False
    device.revoked_at = _now()
    return True


async def get_user_device(db: AsyncSession, user_id: int, device_id: int) -> DesktopDevice | None:
    """Своё неотозванное устройство; чужое и несуществующее неотличимы (None)."""
    return (await db.execute(
        select(DesktopDevice).where(
            DesktopDevice.id == device_id,
            DesktopDevice.user_id == user_id,
            DesktopDevice.revoked_at.is_(None),
        )
    )).scalar_one_or_none()
