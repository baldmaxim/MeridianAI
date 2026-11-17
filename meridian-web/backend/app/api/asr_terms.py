"""API словаря названий для распознавания речи (asr_terms).

Свои термины + общие (owner_user_id IS NULL). Общие создаёт и удаляет только админ.
Читает таблицу services/asr_lexicon.py — новое попадает в распознавание со следующей встречи/задачи.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.asr_term import AsrTerm
from ..models.user import User
from ..schemas.asr_terms import AsrTermCreate, AsrTermOut
from ..services.asr_lexicon import _parse_aliases
from ..services.page_access import require_page

router = APIRouter(dependencies=[Depends(require_page("knowledge"))])


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _key(term: str) -> str:
    return term.strip().lower().replace("ё", "е")


def _to_out(row: AsrTerm, user: User) -> AsrTermOut:
    is_common = row.owner_user_id is None
    return AsrTermOut(
        id=row.id,
        term=row.term,
        aliases=_parse_aliases(row.aliases_json),
        is_common=is_common,
        can_delete=row.owner_user_id == user.id or (is_common and _is_admin(user)),
        created_at=row.created_at,
    )


def _visible(user: User):
    return or_(AsrTerm.owner_user_id.is_(None), AsrTerm.owner_user_id == user.id)


@router.get("", response_model=list[AsrTermOut])
async def list_asr_terms(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(select(AsrTerm).where(_visible(user)))).scalars().all()
    rows = sorted(rows, key=lambda r: (r.term.casefold(), r.id))
    return [_to_out(r, user) for r in rows]


@router.post("", response_model=AsrTermOut, status_code=status.HTTP_201_CREATED)
async def create_asr_term(data: AsrTermCreate, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)):
    if data.common and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Общие названия добавляет только администратор")

    existing = (await db.execute(select(AsrTerm.term).where(_visible(user)))).scalars().all()
    if _key(data.term) in {_key(t) for t in existing}:
        raise HTTPException(status_code=409, detail="Такое название уже есть")

    row = AsrTerm(
        term=data.term,
        aliases_json=json.dumps(data.aliases, ensure_ascii=False),
        owner_user_id=None if data.common else user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row, user)


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asr_term(term_id: int, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)):
    row = await db.get(AsrTerm, term_id)
    if row is None or not (row.owner_user_id is None or row.owner_user_id == user.id):
        raise HTTPException(status_code=404, detail="Название не найдено")
    if row.owner_user_id is None and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Общие названия удаляет только администратор")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
