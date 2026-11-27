"""Прямой семантический поиск по письмам PayHub (внешнее read-only pgvector-хранилище).

POST /api/letters/search — гибридный поиск (вектор+FTS+RRF). 503 если модуль не настроен.
Доступ: has_all (админ/«все проекты») — весь корпус; остальным — только письма проектов PayHub,
привязанных к видимым им объектам (без привязки/видимых объектов — пустой результат).
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config import get_settings
from ..database import get_db
from ..core.rag_letters import list_payhub_projects, search_letters
from ..models.user import User
from ..schemas.letters import LetterSearchHit, LetterSearchRequest, PayhubProject
from ..services.access import accessible_payhub_project_ids

logger = logging.getLogger("meridian.rag_letters")

router = APIRouter()


@router.post("/search", response_model=list[LetterSearchHit])
async def search(
    data: LetterSearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    s = get_settings()
    if not s.letters_rag_effective_enabled:
        raise HTTPException(503, "Поиск по письмам PayHub не настроен")
    query = (data.query or "").strip()
    if not query:
        raise HTTPException(422, "Пустой поисковый запрос")
    k = max(1, min(int(data.k or 8), 50))
    allowed = await accessible_payhub_project_ids(db, user.id)  # None — без ограничений
    if allowed is not None and data.project_id is not None and data.project_id not in allowed:
        return []
    try:
        if allowed is None or data.project_id is not None:
            hits = await search_letters(query, k=k, project_id=data.project_id)
        else:
            # без project_id — только по проектам видимых объектов (хранилище умеет один id)
            if not allowed:
                return []
            per_project = await asyncio.gather(
                *(search_letters(query, k=k, project_id=pid) for pid in allowed)
            )
            merged = {h.chunk_id: h for hits_ in per_project for h in hits_}
            hits = sorted(merged.values(), key=lambda h: h.score, reverse=True)[:k]
    except Exception as e:
        logger.error("letters search failed: %s", e)
        raise HTTPException(502, "Ошибка поиска по письмам") from e
    return [LetterSearchHit(**h.to_dict()) for h in hits]


@router.get("/projects", response_model=list[PayhubProject])
async def projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Проекты PayHub (реальные названия) для связки с нашими объектами.

    Пустой список, если таблица проектов PayHub не настроена (PAYHUB_PROJECTS_TABLE) —
    экран связки покажет «не настроено». 503 — если весь модуль писем выключен.
    """
    s = get_settings()
    if not s.letters_rag_effective_enabled:
        raise HTTPException(503, "Поиск по письмам PayHub не настроен")
    allowed = await accessible_payhub_project_ids(db, user.id)
    try:
        items = await list_payhub_projects()
    except Exception as e:
        logger.error("payhub projects list failed: %s", e)
        raise HTTPException(502, "Ошибка получения проектов PayHub") from e
    if allowed is None:
        return items
    allowed_set = set(allowed)
    return [p for p in items if int(p["projectId"]) in allowed_set]
