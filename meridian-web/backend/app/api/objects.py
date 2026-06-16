"""ProjectObjects directory API + object access grants (Этап 1 MVP)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..services.page_access import require_page
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

# Управление доступом к объекту — это операция справочника "Объекты" (§12).
# Базовый CRUD объектов остаётся общим (нужен странице «Проекты»).
_require_dir_objects = Depends(require_page("dir-objects"))


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


@router.get("/{object_id}/access", response_model=list[ObjectAccessGrantResponse], dependencies=[_require_dir_objects])
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


@router.post("/{object_id}/access", response_model=ObjectAccessGrantResponse, dependencies=[_require_dir_objects])
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


@router.delete("/{object_id}/access/{grant_id}", dependencies=[_require_dir_objects])
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
