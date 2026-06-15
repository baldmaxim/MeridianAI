"""API утверждённой базы знаний (Этап 7).

Только элементы владельца (owner_user_id). 5 списков + архивация. Создаются элементы
исключительно через approve кандидата (api/learning.py) — прямого create здесь нет.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.knowledge import (
    GlossaryTerm, TriggerPhrase, NegotiationPlaybook, CounterpartyTrait, ForbiddenPhrase,
)
from ..schemas.learning import (
    GlossaryTermOut, TriggerPhraseOut, NegotiationPlaybookOut, CounterpartyTraitOut, ForbiddenPhraseOut,
)
from ..auth.dependencies import get_current_user

logger = logging.getLogger("meridian.knowledge")

router = APIRouter()

_KINDS = {
    "terms": GlossaryTerm,
    "triggers": TriggerPhrase,
    "playbooks": NegotiationPlaybook,
    "traits": CounterpartyTrait,
    "forbidden": ForbiddenPhrase,
}


async def _list(model, db, user, status, customer_id, object_id):
    q = select(model).where(model.owner_user_id == user.id)
    if status:
        q = q.where(model.status == status)
    if customer_id is not None:
        q = q.where(model.customer_id == customer_id)
    if object_id is not None:
        q = q.where(model.object_id == object_id)
    return (await db.execute(q.order_by(model.created_at.desc()).limit(1000))).scalars().all()


@router.get("/terms", response_model=list[GlossaryTermOut])
async def list_terms(status: str | None = Query("approved"), customer_id: int | None = Query(None),
                     object_id: int | None = Query(None), db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    return await _list(GlossaryTerm, db, user, status, customer_id, object_id)


@router.get("/triggers", response_model=list[TriggerPhraseOut])
async def list_triggers(status: str | None = Query("approved"), customer_id: int | None = Query(None),
                        object_id: int | None = Query(None), db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return await _list(TriggerPhrase, db, user, status, customer_id, object_id)


@router.get("/playbooks", response_model=list[NegotiationPlaybookOut])
async def list_playbooks(status: str | None = Query("approved"), customer_id: int | None = Query(None),
                         object_id: int | None = Query(None), db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    return await _list(NegotiationPlaybook, db, user, status, customer_id, object_id)


@router.get("/traits", response_model=list[CounterpartyTraitOut])
async def list_traits(status: str | None = Query("approved"), customer_id: int | None = Query(None),
                      object_id: int | None = Query(None), db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return await _list(CounterpartyTrait, db, user, status, customer_id, object_id)


@router.get("/forbidden", response_model=list[ForbiddenPhraseOut])
async def list_forbidden(status: str | None = Query("approved"), customer_id: int | None = Query(None),
                         object_id: int | None = Query(None), db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    return await _list(ForbiddenPhrase, db, user, status, customer_id, object_id)


@router.post("/{kind}/{item_id}/archive")
async def archive_item(kind: str, item_id: int, db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    model = _KINDS.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="Неизвестный раздел базы знаний")
    item = await db.get(model, item_id)
    if item is None or item.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Элемент не найден")
    item.status = "archived"
    await db.commit()
    return {"status": "archived", "kind": kind, "id": item_id}
