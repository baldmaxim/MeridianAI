"""Roles API — CRUD for negotiation roles."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..auth.dependencies import get_current_user
from ..database import async_session
from ..models.user import User
from ..models.role import NegotiationRole
from ..schemas.role import RoleCreate, RoleUpdate, RoleResponse

router = APIRouter()

DEFAULT_ROLE = {
    "name": "Генподрядчик",
    "description": "Генеральный подрядчик в строительной отрасли",
    "interests": "Максимизация прибыли, защита от рисков, контроль качества и сроков",
    "opponents": "Заказчики и субподрядчики",
    "custom_instructions": (
        "Не выдумывай номера договоров, пунктов, статей или документов. "
        "Давай только общие рекомендации, основанные на реальном контексте разговора."
    ),
}


async def _ensure_default_role(user_id: int) -> None:
    """Create default role if user has no roles."""
    async with async_session() as db:
        result = await db.execute(
            select(NegotiationRole).where(NegotiationRole.user_id == user_id).limit(1)
        )
        if result.scalar_one_or_none() is None:
            role = NegotiationRole(
                user_id=user_id, is_default=True, **DEFAULT_ROLE
            )
            db.add(role)
            await db.commit()


@router.get("", response_model=list[RoleResponse])
async def list_roles(user: User = Depends(get_current_user)):
    await _ensure_default_role(user.id)
    async with async_session() as db:
        result = await db.execute(
            select(NegotiationRole)
            .where(NegotiationRole.user_id == user.id)
            .order_by(NegotiationRole.is_default.desc(), NegotiationRole.created_at)
        )
        return result.scalars().all()


@router.post("", response_model=RoleResponse)
async def create_role(
    data: RoleCreate,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        role = NegotiationRole(user_id=user.id, is_default=False, **data.model_dump())
        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role


@router.put("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int,
    data: RoleUpdate,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        result = await db.execute(
            select(NegotiationRole).where(
                NegotiationRole.id == role_id,
                NegotiationRole.user_id == user.id,
            )
        )
        role = result.scalar_one_or_none()
        if not role:
            raise HTTPException(404, "Role not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(role, key, value)
        await db.commit()
        await db.refresh(role)
        return role


@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    user: User = Depends(get_current_user),
):
    async with async_session() as db:
        result = await db.execute(
            select(NegotiationRole).where(
                NegotiationRole.id == role_id,
                NegotiationRole.user_id == user.id,
            )
        )
        role = result.scalar_one_or_none()
        if not role:
            raise HTTPException(404, "Role not found")
        if role.is_default:
            raise HTTPException(400, "Cannot delete default role")
        await db.delete(role)
        await db.commit()
        return {"ok": True}
