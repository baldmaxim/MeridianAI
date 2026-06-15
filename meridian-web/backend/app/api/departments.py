"""Departments directory API + user membership (Этап 1 MVP)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.directory import Department, UserDepartment
from ..schemas.directory import (
    DepartmentCreate,
    DepartmentUpdate,
    DepartmentResponse,
    DepartmentUserResponse,
)

router = APIRouter()


@router.get("", response_model=list[DepartmentResponse])
async def list_departments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Department).order_by(Department.name))
    return result.scalars().all()


@router.post("", response_model=DepartmentResponse)
async def create_department(
    data: DepartmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dept = Department(owner_user_id=user.id, **data.model_dump())
    db.add(dept)
    await db.flush()
    await db.refresh(dept)
    return dept


@router.get("/{department_id}", response_model=DepartmentResponse)
async def get_department(
    department_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dept = await db.get(Department, department_id)
    if not dept:
        raise HTTPException(404, "Отдел не найден")
    return dept


@router.put("/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: int,
    data: DepartmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dept = await db.get(Department, department_id)
    if not dept:
        raise HTTPException(404, "Отдел не найден")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(dept, key, value)
    await db.flush()
    await db.refresh(dept)
    return dept


@router.delete("/{department_id}")
async def delete_department(
    department_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dept = await db.get(Department, department_id)
    if not dept:
        raise HTTPException(404, "Отдел не найден")
    await db.delete(dept)
    await db.flush()
    return {"ok": True}


# --- User membership ---


@router.get("/{department_id}/users", response_model=list[DepartmentUserResponse])
async def list_department_users(
    department_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dept = await db.get(Department, department_id)
    if not dept:
        raise HTTPException(404, "Отдел не найден")
    result = await db.execute(
        select(UserDepartment, User)
        .join(User, User.id == UserDepartment.user_id)
        .where(UserDepartment.department_id == department_id)
        .order_by(User.email)
    )
    return [
        DepartmentUserResponse(
            membership_id=ud.id,
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            created_at=ud.created_at,
        )
        for ud, u in result.all()
    ]


@router.post("/{department_id}/users/{user_id}", response_model=DepartmentUserResponse)
async def add_department_user(
    department_id: int,
    user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    dept = await db.get(Department, department_id)
    if not dept:
        raise HTTPException(404, "Отдел не найден")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Пользователь не найден")

    existing = await db.execute(
        select(UserDepartment).where(
            UserDepartment.department_id == department_id,
            UserDepartment.user_id == user_id,
        )
    )
    membership = existing.scalar_one_or_none()
    if membership is None:
        membership = UserDepartment(user_id=user_id, department_id=department_id)
        db.add(membership)
        await db.flush()
        await db.refresh(membership)

    return DepartmentUserResponse(
        membership_id=membership.id,
        user_id=target.id,
        email=target.email,
        display_name=target.display_name,
        created_at=membership.created_at,
    )


@router.delete("/{department_id}/users/{user_id}")
async def remove_department_user(
    department_id: int,
    user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserDepartment).where(
            UserDepartment.department_id == department_id,
            UserDepartment.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(404, "Сотрудник не состоит в отделе")
    await db.delete(membership)
    await db.flush()
    return {"ok": True}
