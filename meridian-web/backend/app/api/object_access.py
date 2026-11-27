"""Ручной доступ к проектам: заявки сотрудников и управление грантами (админ)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user, require_admin
from ..database import get_db
from ..models.directory import Customer, ProjectObject
from ..models.object_access import ObjectAccessRequest, UserCustomerAccess, UserObjectAccess
from ..models.user import User
from ..schemas.object_access import (
    ObjectAccessRequestOut,
    ObjectAccessRequestStatus,
    UserObjectAccessPayload,
)
from ..services.access import user_can_access_object
from ..services.audit import audit, client_ip

# /api/objects/{id}/access-request — любой авторизованный
router = APIRouter()
# /api/admin/... — только админ
admin_router = APIRouter()

REQUEST_STATUSES = ("pending", "approved", "rejected")


@router.post("/{object_id}/access-request", response_model=ObjectAccessRequestStatus)
async def request_object_access(
    object_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Заявка на доступ к объекту. Идемпотентна: повтор не плодит заявок."""
    if await db.get(ProjectObject, object_id) is None:
        raise HTTPException(404, "Объект не найден")
    if await user_can_access_object(db, user.id, object_id):
        return ObjectAccessRequestStatus(status="already_granted")
    pending = await db.scalar(
        select(ObjectAccessRequest.id).where(
            ObjectAccessRequest.user_id == user.id,
            ObjectAccessRequest.object_id == object_id,
            ObjectAccessRequest.status == "pending",
        )
    )
    if pending is not None:
        return ObjectAccessRequestStatus(status="pending")
    try:
        async with db.begin_nested():
            db.add(ObjectAccessRequest(user_id=user.id, object_id=object_id, status="pending"))
    except IntegrityError:
        return ObjectAccessRequestStatus(status="pending")  # параллельный дубль
    await audit("object_access_requested", actor_user_id=user.id, ip=client_ip(request),
                object_id=object_id)
    return ObjectAccessRequestStatus(status="pending")


@admin_router.get("/object-access-requests", response_model=list[ObjectAccessRequestOut])
async def list_access_requests(
    status: str = Query("pending"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if status not in REQUEST_STATUSES:
        raise HTTPException(422, "Недопустимый статус заявки")
    rows = (
        await db.execute(
            select(ObjectAccessRequest, User, ProjectObject, Customer.name)
            .join(User, User.id == ObjectAccessRequest.user_id)
            .join(ProjectObject, ProjectObject.id == ObjectAccessRequest.object_id)
            .join(Customer, Customer.id == ProjectObject.customer_id)
            .where(ObjectAccessRequest.status == status)
            .order_by(ObjectAccessRequest.created_at.desc(), ObjectAccessRequest.id.desc())
        )
    ).all()
    return [
        ObjectAccessRequestOut(
            id=req.id, user_id=u.id, user_email=u.email, user_display_name=u.display_name,
            object_id=obj.id, object_name=obj.name, customer_name=customer_name,
            status=req.status, created_at=req.created_at,
        )
        for req, u, obj, customer_name in rows
    ]


async def _decide(
    request_id: int, new_status: str, request: Request, admin: User, db: AsyncSession,
) -> ObjectAccessRequestStatus:
    req = await db.get(ObjectAccessRequest, request_id)
    if req is None:
        raise HTTPException(404, "Заявка не найдена")
    if req.status != "pending":
        raise HTTPException(409, "Заявка уже обработана")
    if new_status == "approved":
        exists = await db.scalar(
            select(UserObjectAccess.user_id).where(
                UserObjectAccess.user_id == req.user_id,
                UserObjectAccess.object_id == req.object_id,
            )
        )
        if exists is None:
            db.add(UserObjectAccess(
                user_id=req.user_id, object_id=req.object_id, granted_by_user_id=admin.id,
            ))
    req.status = new_status
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by_user_id = admin.id
    await db.flush()
    await audit(f"object_access_request_{new_status}", actor_user_id=admin.id,
                ip=client_ip(request), request_id=req.id, target_user_id=req.user_id,
                object_id=req.object_id)
    return ObjectAccessRequestStatus(status=new_status)


@admin_router.post("/object-access-requests/{request_id}/approve",
                   response_model=ObjectAccessRequestStatus)
async def approve_access_request(
    request_id: int, request: Request,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    return await _decide(request_id, "approved", request, admin, db)


@admin_router.post("/object-access-requests/{request_id}/reject",
                   response_model=ObjectAccessRequestStatus)
async def reject_access_request(
    request_id: int, request: Request,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    return await _decide(request_id, "rejected", request, admin, db)


async def _load_payload(db: AsyncSession, user: User) -> UserObjectAccessPayload:
    customer_ids = (await db.execute(
        select(UserCustomerAccess.customer_id)
        .where(UserCustomerAccess.user_id == user.id).order_by(UserCustomerAccess.customer_id)
    )).scalars().all()
    object_ids = (await db.execute(
        select(UserObjectAccess.object_id)
        .where(UserObjectAccess.user_id == user.id).order_by(UserObjectAccess.object_id)
    )).scalars().all()
    return UserObjectAccessPayload(
        all_objects=bool(user.all_objects_access),
        customer_ids=list(customer_ids), object_ids=list(object_ids),
    )


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


@admin_router.get("/users/{user_id}/object-access", response_model=UserObjectAccessPayload)
async def get_user_object_access(
    user_id: int,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    return await _load_payload(db, await _get_user_or_404(db, user_id))


@admin_router.put("/users/{user_id}/object-access", response_model=UserObjectAccessPayload)
async def put_user_object_access(
    user_id: int, data: UserObjectAccessPayload, request: Request,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """Полная замена грантов пользователя (и флага «все проекты»)."""
    user = await _get_user_or_404(db, user_id)
    customer_ids = set(data.customer_ids)
    object_ids = set(data.object_ids)
    if customer_ids:
        found = set((await db.execute(
            select(Customer.id).where(Customer.id.in_(customer_ids))
        )).scalars().all())
        if found != customer_ids:
            raise HTTPException(422, "Заказчик не найден")
    if object_ids:
        found = set((await db.execute(
            select(ProjectObject.id).where(ProjectObject.id.in_(object_ids))
        )).scalars().all())
        if found != object_ids:
            raise HTTPException(422, "Объект не найден")

    user.all_objects_access = data.all_objects

    old_customers = set((await db.execute(
        select(UserCustomerAccess.customer_id).where(UserCustomerAccess.user_id == user.id)
    )).scalars().all())
    old_objects = set((await db.execute(
        select(UserObjectAccess.object_id).where(UserObjectAccess.user_id == user.id)
    )).scalars().all())
    # неизменённые строки не трогаем — сохраняются автор выдачи и дата
    if old_customers - customer_ids:
        await db.execute(delete(UserCustomerAccess).where(
            UserCustomerAccess.user_id == user.id,
            UserCustomerAccess.customer_id.in_(old_customers - customer_ids),
        ))
    if old_objects - object_ids:
        await db.execute(delete(UserObjectAccess).where(
            UserObjectAccess.user_id == user.id,
            UserObjectAccess.object_id.in_(old_objects - object_ids),
        ))
    for cid in sorted(customer_ids - old_customers):
        db.add(UserCustomerAccess(user_id=user.id, customer_id=cid, granted_by_user_id=admin.id))
    for oid in sorted(object_ids - old_objects):
        db.add(UserObjectAccess(user_id=user.id, object_id=oid, granted_by_user_id=admin.id))
    await db.flush()

    await audit("object_access_changed", actor_user_id=admin.id, ip=client_ip(request),
                target_user_id=user.id, all_objects=data.all_objects,
                customer_count=len(customer_ids), object_count=len(object_ids))
    return await _load_payload(db, user)
