"""Customers directory API.

Читать можно только видимых заказчиков (has_all, грант заказчика или видимый объект);
править/удалять — только has_all. owner_user_id фиксирует создателя.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.directory import Customer, ProjectObject
from ..schemas.directory import CustomerCreate, CustomerUpdate, CustomerResponse
from ..services.access import (
    accessible_customer_ids_select,
    user_can_access_customer,
    user_has_all_objects,
)

router = APIRouter()

# Справочников больше нет: заказчик создаётся на лету при добавлении объекта.
# Чтение — по видимости, прямые мутации (PUT/DELETE) — только has_all.


async def _require_has_all(db: AsyncSession, user: User) -> None:
    if not await user_has_all_objects(db, user.id):
        raise HTTPException(403, "Недостаточно прав")


@router.get("", response_model=list[CustomerResponse])
async def list_customers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Customer)
        .where(Customer.id.in_(accessible_customer_ids_select(user.id)))
        .order_by(Customer.name)
    )
    return result.scalars().all()


@router.post("", response_model=CustomerResponse)
async def create_customer(
    data: CustomerCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    customer = Customer(owner_user_id=user.id, **data.model_dump())
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    customer = await db.get(Customer, customer_id)
    if customer is None or not await user_can_access_customer(db, user.id, customer_id):
        raise HTTPException(404, "Заказчик не найден")
    return customer


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_has_all(db, user)
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Заказчик не найден")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(customer, key, value)
    await db.flush()
    await db.refresh(customer)
    return customer


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_has_all(db, user)
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Заказчик не найден")
    # Защита от каскадного удаления объектов: запрещаем удалять заказчика с объектами
    obj_count = await db.scalar(
        select(func.count(ProjectObject.id)).where(ProjectObject.customer_id == customer_id)
    )
    if obj_count:
        raise HTTPException(400, "Нельзя удалить заказчика с объектами")
    await db.delete(customer)
    await db.flush()
    return {"ok": True}
