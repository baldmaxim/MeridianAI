"""API кандидатов авто-обучения (Этап 7).

Кандидаты владельца (owner_user_id == текущий пользователь). approve создаёт
элемент базы знаний; reject помечает rejected. Ручной запуск extraction по встрече.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.knowledge import LearningCandidate
from ..schemas.learning import LearningCandidateResponse, LearningCandidatePatch, _conf
from ..auth.dependencies import get_current_user
from ..services.access import user_can_access_meeting
from ..services.learning_approve import approve_candidate
from ..services.learning_extract import request_learning_extraction

logger = logging.getLogger("meridian.learning")

router = APIRouter()


def _to_response(c: LearningCandidate) -> LearningCandidateResponse:
    return LearningCandidateResponse(
        id=c.id, owner_user_id=c.owner_user_id, customer_id=c.customer_id, object_id=c.object_id,
        meeting_id=c.meeting_id, candidate_type=c.candidate_type, title=c.title,
        payload=json.loads(c.payload_json) if c.payload_json else {},
        source_text=c.source_text,
        source_refs=json.loads(c.source_refs_json) if c.source_refs_json else [],
        confidence=c.confidence, status=c.status, reviewed_by_user_id=c.reviewed_by_user_id,
        reviewed_at=c.reviewed_at, created_at=c.created_at, updated_at=c.updated_at,
    )


async def _get_owned(db: AsyncSession, candidate_id: int, user: User) -> LearningCandidate:
    cand = await db.get(LearningCandidate, candidate_id)
    if cand is None or cand.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    return cand


@router.get("/learning/candidates", response_model=list[LearningCandidateResponse])
async def list_candidates(
    status: str | None = Query("pending"),
    candidate_type: str | None = Query(None),
    meeting_id: int | None = Query(None),
    customer_id: int | None = Query(None),
    object_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(LearningCandidate).where(LearningCandidate.owner_user_id == user.id)
    if status:
        q = q.where(LearningCandidate.status == status)
    if candidate_type:
        q = q.where(LearningCandidate.candidate_type == candidate_type)
    if meeting_id is not None:
        q = q.where(LearningCandidate.meeting_id == meeting_id)
    if customer_id is not None:
        q = q.where(LearningCandidate.customer_id == customer_id)
    if object_id is not None:
        q = q.where(LearningCandidate.object_id == object_id)
    q = q.order_by(LearningCandidate.created_at.desc()).limit(500)
    rows = (await db.execute(q)).scalars().all()
    return [_to_response(c) for c in rows]


@router.get("/learning/candidates/{candidate_id}", response_model=LearningCandidateResponse)
async def get_candidate(candidate_id: int, db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return _to_response(await _get_owned(db, candidate_id, user))


@router.patch("/learning/candidates/{candidate_id}", response_model=LearningCandidateResponse)
async def patch_candidate(candidate_id: int, patch: LearningCandidatePatch,
                          db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cand = await _get_owned(db, candidate_id, user)
    if cand.status != "pending":
        raise HTTPException(status_code=409, detail="Можно редактировать только pending-кандидата")
    if patch.title is not None:
        cand.title = patch.title[:300]
    if patch.payload is not None:
        cand.payload_json = json.dumps(patch.payload, ensure_ascii=False)
    if patch.source_text is not None:
        cand.source_text = patch.source_text
    if patch.confidence is not None:
        cand.confidence = _conf(patch.confidence)
    await db.commit()
    await db.refresh(cand)
    return _to_response(cand)


@router.post("/learning/candidates/{candidate_id}/approve", response_model=LearningCandidateResponse)
async def approve(candidate_id: int, db: AsyncSession = Depends(get_db),
                  user: User = Depends(get_current_user)):
    cand = await _get_owned(db, candidate_id, user)
    if cand.status != "pending":
        raise HTTPException(status_code=409, detail="Кандидат уже обработан")
    item = await approve_candidate(db, cand, user.id)
    if item is None:
        raise HTTPException(status_code=422, detail="Неизвестный тип кандидата")
    await db.commit()
    await db.refresh(cand)
    logger.info("learning candidate %s approved by user %s (%s)", candidate_id, user.id, cand.candidate_type)
    return _to_response(cand)


@router.post("/learning/candidates/{candidate_id}/reject", response_model=LearningCandidateResponse)
async def reject(candidate_id: int, db: AsyncSession = Depends(get_db),
                 user: User = Depends(get_current_user)):
    from datetime import datetime
    cand = await _get_owned(db, candidate_id, user)
    if cand.status != "pending":
        raise HTTPException(status_code=409, detail="Кандидат уже обработан")
    cand.status = "rejected"
    cand.reviewed_by_user_id = user.id
    cand.reviewed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(cand)
    return _to_response(cand)


@router.post("/meetings/{meeting_id}/learning/extract")
async def trigger_extraction(meeting_id: int, db: AsyncSession = Depends(get_db),
                             user: User = Depends(get_current_user)):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(status_code=403, detail="Нет доступа к встрече")
    ok = await request_learning_extraction(db, meeting_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Извлечение знаний отключено или встреча не найдена")
    await db.commit()
    return {"status": "queued", "meeting_id": meeting_id}
