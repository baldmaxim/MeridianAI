"""ProjectObjects API. Объект виден по правилам app/services/access.py (гранты/все проекты)."""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.user import User
from ..models.directory import Customer, ProjectObject
from ..models.object_access import UserObjectAccess
from ..schemas.directory import (
    ProjectObjectCreate,
    ProjectObjectUpdate,
    ProjectObjectResponse,
)
from ..schemas.document import OfferSubmission
from ..services.access import (
    accessible_object_ids_select,
    user_can_access_object,
    user_has_all_objects,
)
from ..services.audit import audit, client_ip
from ..services.offer_submissions import list_object_offer_submissions

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


_QUOTES_RE = re.compile(r"[«»\"'„“”‟`]")
_PUNCT_RE = re.compile(r"[^\w\s]|_")
MIN_FUZZY_LEN = 4


def normalize_object_text(value: str | None) -> str:
    """Нормализация имени/адреса для поиска дублей: регистр, ё, кавычки, пунктуация, «жк»."""
    text = (value or "").lower().replace("ё", "е")
    text = _QUOTES_RE.sub("", text)
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(t for t in text.split() if t != "жк")


async def _find_duplicate_candidates(
    db: AsyncSession, user_id: int, has_all: bool, name: str, address: str | None, customer_name: str,
) -> tuple[bool, list[dict]]:
    """Похожие объекты среди ВСЕХ (включая невидимые). Возвращает (есть_точное, кандидаты)."""
    norm_name = normalize_object_text(name)
    norm_addr = normalize_object_text(address)
    customer_key = customer_name.strip().casefold()
    rows = (
        await db.execute(
            select(
                ProjectObject.id, ProjectObject.name, ProjectObject.address, Customer.name,
            ).join(Customer, Customer.id == ProjectObject.customer_id)
        )
    ).all()
    visible: set[int] = set()
    if not has_all and rows:
        visible = set((await db.execute(accessible_object_ids_select(user_id))).scalars().all())

    exact_found = False
    candidates: list[dict] = []
    for obj_id, obj_name, obj_address, obj_customer in rows:
        other_name = normalize_object_text(obj_name)
        same_name = bool(norm_name) and norm_name == other_name
        same_customer = (obj_customer or "").strip().casefold() == customer_key
        exact = same_name and same_customer
        fuzzy = (
            same_name
            or (
                bool(norm_name) and bool(other_name)
                and min(len(norm_name), len(other_name)) >= MIN_FUZZY_LEN
                and (norm_name in other_name or other_name in norm_name)
            )
            or (bool(norm_addr) and norm_addr == normalize_object_text(obj_address))
        )
        if not (exact or fuzzy):
            continue
        exact_found = exact_found or exact
        candidates.append({
            "id": obj_id,
            "name": obj_name,
            "customer_name": obj_customer,
            "has_access": has_all or obj_id in visible,
            "_exact": exact,
        })
    return exact_found, candidates


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
        .where(ProjectObject.id.in_(accessible_object_ids_select(user.id)))
    )
    if customer_id is not None:
        stmt = stmt.where(ProjectObject.customer_id == customer_id)
    stmt = stmt.order_by(ProjectObject.name)
    rows = (await db.execute(stmt)).all()
    return [_obj_response(obj, cname) for obj, cname in rows]


@router.post("", response_model=ProjectObjectResponse)
async def create_object(
    data: ProjectObjectCreate,
    request: Request = None,  # инжектится FastAPI; None — при прямом вызове в тестах
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать объект. Похожие объекты → 409 duplicate_object (заказчик ещё не создаётся)."""
    customer_name = (data.customer_name or "").strip()
    if not customer_name:
        raise HTTPException(422, "Укажите заказчика")
    has_all = await user_has_all_objects(db, user.id)
    exact, candidates = await _find_duplicate_candidates(
        db, user.id, has_all, data.name, data.address, customer_name
    )
    # Точное совпадение: обычному сотруднику — всегда стоп (force игнорируется), админ может
    # создать. Только нечёткое совпадение — стоп, пока нет force («создать всё равно»).
    if candidates and (
        (exact and user.role != "admin") or (not exact and not data.force)
    ):
        raise HTTPException(
            409,
            detail={
                "code": "duplicate_object",
                "exact": exact,
                "candidates": [{k: v for k, v in c.items() if k != "_exact"} for c in candidates],
            },
        )
    customer = await resolve_or_create_customer(db, user.id, customer_name)
    obj = ProjectObject(
        owner_user_id=user.id,
        customer_id=customer.id,
        name=data.name,
        address=data.address,
        description=data.description,
        notes=data.notes,
        payhub_project_id=data.payhub_project_id,
        is_active=data.is_active,
        tender_won=data.tender_won,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    if not has_all:
        # создатель не должен потерять только что созданный проект
        db.add(UserObjectAccess(user_id=user.id, object_id=obj.id, granted_by_user_id=user.id))
        await db.flush()
    await audit("object_created", actor_user_id=user.id, ip=client_ip(request), object_id=obj.id)
    return _obj_response(obj, customer.name)


@router.get("/{object_id}", response_model=ProjectObjectResponse)
async def get_object(
    object_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ProjectObject, object_id)
    if not obj or not await user_can_access_object(db, user.id, object_id):
        raise HTTPException(404, "Объект не найден")
    customer = await db.get(Customer, obj.customer_id)
    return _obj_response(obj, customer.name if customer else None)


@router.get("/{object_id}/offer-submissions", response_model=list[OfferSubmission])
async def list_offer_submissions(
    object_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Подачи КП объекта: группы документов по offer_submission (новые сверху)."""
    if await db.get(ProjectObject, object_id) is None:
        raise HTTPException(404, "Объект не найден")
    if not await user_can_access_object(db, user.id, object_id):
        raise HTTPException(403, "Нет доступа к объекту")
    return [
        OfferSubmission(key=g.key, label=g.label, date=g.date, document_count=g.document_count)
        for g in await list_object_offer_submissions(db, object_id)
    ]


@router.put("/{object_id}", response_model=ProjectObjectResponse)
async def update_object(
    object_id: int,
    data: ProjectObjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ProjectObject, object_id)
    if not obj or not await user_can_access_object(db, user.id, object_id):
        raise HTTPException(404, "Объект не найден")
    updates = data.model_dump(exclude_unset=True)
    if updates.get("tender_won", True) is None:
        updates.pop("tender_won")  # NOT NULL: явный null = «не менять»
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
    if not obj or not await user_can_access_object(db, user.id, object_id):
        raise HTTPException(404, "Объект не найден")
    await db.delete(obj)
    await db.flush()
    return {"ok": True}
