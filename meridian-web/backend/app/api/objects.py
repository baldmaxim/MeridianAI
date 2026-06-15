"""ProjectObjects directory API + object access grants (Этап 1 MVP)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.directory import Customer, ProjectObject, Department, ObjectAccessGrant
from ..schemas.directory import (
    ProjectObjectCreate,
    ProjectObjectUpdate,
    ProjectObjectResponse,
    ObjectAccessGrantCreate,
    ObjectAccessGrantResponse,
)

router = APIRouter()


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
    customer = await db.get(Customer, data.customer_id)
    if not customer:
        raise HTTPException(422, "Заказчик не найден")
    obj = ProjectObject(owner_user_id=user.id, **data.model_dump())
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
    if "customer_id" in updates and updates["customer_id"] is not None:
        customer = await db.get(Customer, updates["customer_id"])
        if not customer:
            raise HTTPException(422, "Заказчик не найден")
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


# --- Object access grants ---


async def _grant_response(db: AsyncSession, grant: ObjectAccessGrant) -> ObjectAccessGrantResponse:
    resp = ObjectAccessGrantResponse.model_validate(grant)
    if grant.grantee_type == "user" and grant.grantee_user_id:
        u = await db.get(User, grant.grantee_user_id)
        if u:
            resp.grantee_name = u.display_name or u.email
    elif grant.grantee_type == "department" and grant.grantee_department_id:
        d = await db.get(Department, grant.grantee_department_id)
        if d:
            resp.grantee_name = d.name
    return resp


@router.get("/{object_id}/access", response_model=list[ObjectAccessGrantResponse])
async def list_object_access(
    object_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ProjectObject, object_id)
    if not obj:
        raise HTTPException(404, "Объект не найден")
    result = await db.execute(
        select(ObjectAccessGrant)
        .where(ObjectAccessGrant.object_id == object_id)
        .order_by(ObjectAccessGrant.created_at)
    )
    return [await _grant_response(db, g) for g in result.scalars().all()]


@router.post("/{object_id}/access", response_model=ObjectAccessGrantResponse)
async def create_object_access(
    object_id: int,
    data: ObjectAccessGrantCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ProjectObject, object_id)
    if not obj:
        raise HTTPException(404, "Объект не найден")

    if data.grantee_type == "user":
        if not data.grantee_user_id:
            raise HTTPException(422, "Для типа 'user' нужен grantee_user_id")
        if not await db.get(User, data.grantee_user_id):
            raise HTTPException(422, "Пользователь не найден")
        grantee_department_id = None
        grantee_user_id = data.grantee_user_id
    else:  # department
        if not data.grantee_department_id:
            raise HTTPException(422, "Для типа 'department' нужен grantee_department_id")
        if not await db.get(Department, data.grantee_department_id):
            raise HTTPException(422, "Отдел не найден")
        grantee_user_id = None
        grantee_department_id = data.grantee_department_id

    grant = ObjectAccessGrant(
        object_id=object_id,
        grantee_type=data.grantee_type,
        grantee_user_id=grantee_user_id,
        grantee_department_id=grantee_department_id,
        access_level=data.access_level,
        created_by_user_id=user.id,
    )
    db.add(grant)
    await db.flush()
    await db.refresh(grant)
    return await _grant_response(db, grant)


@router.delete("/{object_id}/access/{grant_id}")
async def delete_object_access(
    object_id: int,
    grant_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    grant = await db.get(ObjectAccessGrant, grant_id)
    if not grant or grant.object_id != object_id:
        raise HTTPException(404, "Грант не найден")
    await db.delete(grant)
    await db.flush()
    return {"ok": True}
