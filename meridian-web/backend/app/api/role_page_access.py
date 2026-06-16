"""Admin API: матрица доступа к страницам по ролям (page-access).

GET  /api/admin/page-access            — каталог + конфиги ролей admin/user.
PUT  /api/admin/page-access/{role}     — заменить набор страниц роли.

Защита от локаута: always-allowed (objects для всех, settings для admin)
до-добавляются серверно и не могут быть сняты.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_admin
from ..core.pages import (
    PAGE_CATALOG,
    always_allowed_for,
    default_pages_for,
    normalize_allowed,
)
from ..database import get_db
from ..models.role_page_access import RolePageAccess
from ..models.user import User
from ..schemas.role_page_access import RolePageAccessResponse, RolePageAccessUpdate
from ..services.audit import audit, client_ip

router = APIRouter()

ROLES = ["admin", "user"]


async def _get_or_create_row(db: AsyncSession, role_name: str) -> RolePageAccess:
    row = (
        await db.execute(
            select(RolePageAccess).where(RolePageAccess.role_name == role_name)
        )
    ).scalar_one_or_none()
    if row is None:
        row = RolePageAccess(
            role_name=role_name,
            allowed_pages=json.dumps(default_pages_for(role_name), ensure_ascii=False),
        )
        db.add(row)
        await db.flush()
    return row


@router.get("")
async def get_page_access(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    roles = []
    for r in ROLES:
        row = await _get_or_create_row(db, r)
        roles.append(RolePageAccessResponse.model_validate(row).model_dump())
    return {
        "catalog": PAGE_CATALOG,
        "roles": roles,
        "locked": {r: sorted(always_allowed_for(r)) for r in ROLES},
    }


@router.put("/{role_name}", response_model=RolePageAccessResponse)
async def update_page_access(
    role_name: str,
    data: RolePageAccessUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if role_name not in ROLES:
        raise HTTPException(404, "Неизвестная роль")

    row = await _get_or_create_row(db, role_name)
    old = row.allowed_pages
    new_keys = normalize_allowed(role_name, data.allowed_pages)
    row.allowed_pages = json.dumps(new_keys, ensure_ascii=False)
    await db.flush()

    await audit(
        "role_page_access_changed",
        actor_user_id=admin.id,
        ip=client_ip(request),
        role=role_name,
        old=old,
        new=row.allowed_pages,
    )
    return RolePageAccessResponse.model_validate(row)
