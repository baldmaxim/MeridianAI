"""Page-access: разрешение страниц по роли + FastAPI-гард enforcement."""

import json

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.pages import PAGE_KEYS, always_allowed_for, default_pages_for
from ..database import get_db
from ..models.role_page_access import RolePageAccess
from ..models.user import User
from ..auth.dependencies import get_current_user


async def get_allowed_pages(db: AsyncSession, role_name: str) -> set[str]:
    """Разрешённые ключи страниц для роли (с учётом always-allowed).

    Нет строки в БД → дефолты роли. Битый JSON → only always-allowed.
    Неизвестные ключи отбрасываются.
    """
    row = (
        await db.execute(
            select(RolePageAccess).where(RolePageAccess.role_name == role_name)
        )
    ).scalar_one_or_none()

    if row is None:
        return set(default_pages_for(role_name))

    try:
        keys = set(json.loads(row.allowed_pages))
    except Exception:
        keys = set()
    return {k for k in keys if k in PAGE_KEYS} | always_allowed_for(role_name)


def require_page(page_key: str):
    """Фабрика зависимости: 403, если у роли пользователя нет доступа к page_key."""

    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        allowed = await get_allowed_pages(db, user.role)
        if page_key not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Доступ к разделу запрещён",
            )
        return user

    return _dep
