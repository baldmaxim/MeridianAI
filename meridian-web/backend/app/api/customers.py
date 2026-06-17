"""Customers directory API (Этап 1 MVP).

Scope — общий для фирмы: все авторизованные читают и управляют.
owner_user_id фиксирует создателя (seam под будущий organization_id).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.directory import Customer, ProjectObject
from ..schemas.directory import CustomerCreate, CustomerUpdate, CustomerResponse

router = APIRouter()

# Справочников больше нет: заказчик создаётся на лету при добавлении объекта.
# Чтение и редкие прямые мутации доступны любому авторизованному.


@router.get("", response_model=list[CustomerResponse])
async def list_customers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Customer).order_by(Customer.name))
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
    if not customer:
        raise HTTPException(404, "Заказчик не найден")
    return customer


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
