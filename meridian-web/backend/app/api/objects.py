"""ProjectObjects API (Этап 1 MVP). Объект виден только владельцу/создателю."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.directory import Customer, ProjectObject
from ..schemas.directory import (
    ProjectObjectCreate,
    ProjectObjectUpdate,
    ProjectObjectResponse,
)

router = APIRouter()


async def resolve_or_create_customer(
    db: AsyncSession, owner_user_id: int, name: str | None
) -> Customer:
    """Найти заказчика по имени (в рамках фирмы) или создать нового.

    Заказчики больше не ведутся отдельным справочником — создаются на лету при
    добавлении объекта/встречи. Поиск company-wide (как list_customers), регистр игнорируем.
    """
    clean = (name or "").strip()
    if not clean:
        raise HTTPException(422, "Укажите заказчика")
    existing = (
        await db.execute(
            select(Customer).where(func.lower(Customer.name) == clean.lower())
        )
    ).scalars().first()
    if existing:
        return existing
    customer = Customer(owner_user_id=owner_user_id, name=clean)
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    return customer


def _obj_response(obj: ProjectObject, customer_name: str | None = None) -> ProjectObjectResponse:
    resp = ProjectObjectResponse.model_validate(obj)
    resp.customer_name = customer_name
    return resp


@router.get("", response_model=list[ProjectObjectResponse])
async def list_objects(
    customer_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ProjectObject, Customer.name)
        .join(Customer, Customer.id == ProjectObject.customer_id)
    )
    if customer_id is not None:
        stmt = stmt.where(ProjectObject.customer_id == customer_id)
    stmt = stmt.order_by(ProjectObject.name)
    rows = (await db.execute(stmt)).all()
    return [_obj_response(obj, cname) for obj, cname in rows]


@router.post("", response_model=ProjectObjectResponse)
async def create_object(
    data: ProjectObjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    customer = await resolve_or_create_customer(db, user.id, data.customer_name)
    obj = ProjectObject(
        owner_user_id=user.id,
        customer_id=customer.id,
        name=data.name,
        address=data.address,
        description=data.description,
        notes=data.notes,
        is_active=data.is_active,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return _obj_response(obj, customer.name)


@router.get("/{object_id}", response_model=ProjectObjectResponse)
async def get_object(
    object_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ProjectObject, object_id)
    if not obj:
        raise HTTPException(404, "Объект не найден")
    customer = await db.get(Customer, obj.customer_id)
    return _obj_response(obj, customer.name if customer else None)


@router.put("/{object_id}", response_model=ProjectObjectResponse)
async def update_object(
    object_id: int,
    data: ProjectObjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ProjectObject, object_id)
    if not obj:
        raise HTTPException(404, "Объект не найден")
    updates = data.model_dump(exclude_unset=True)
    if "customer_name" in updates:
        customer = await resolve_or_create_customer(db, user.id, updates.pop("customer_name"))
        obj.customer_id = customer.id
    for key, value in updates.items():
        setattr(obj, key, value)
    await db.flush()
    await db.refresh(obj)
    customer = await db.get(Customer, obj.customer_id)
    return _obj_response(obj, customer.name if customer else None)


@router.delete("/{object_id}")
async def delete_object(
    object_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ProjectObject, object_id)
    if not obj:
        raise HTTPException(404, "Объект не найден")
    await db.delete(obj)
    await db.flush()
    return {"ok": True}
