"""Прямой семантический поиск по письмам PayHub (внешнее read-only pgvector-хранилище).

POST /api/letters/search — гибридный поиск (вектор+FTS+RRF). 503 если модуль не настроен.
Доступ — любой авторизованный пользователь (корпус read-only, без PII-фильтра на стороне БД).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..auth.dependencies import get_current_user
from ..config import get_settings
from ..core.rag_letters import list_payhub_projects, search_letters
from ..models.user import User
from ..schemas.letters import LetterSearchHit, LetterSearchRequest, PayhubProject

logger = logging.getLogger("meridian.rag_letters")

router = APIRouter()


@router.post("/search", response_model=list[LetterSearchHit])
async def search(
    data: LetterSearchRequest,
    user: User = Depends(get_current_user),
):
    s = get_settings()
    if not s.letters_rag_effective_enabled:
        raise HTTPException(503, "Поиск по письмам PayHub не настроен")
    query = (data.query or "").strip()
    if not query:
        raise HTTPException(422, "Пустой поисковый запрос")
    k = max(1, min(int(data.k or 8), 50))
    try:
        hits = await search_letters(query, k=k, project_id=data.project_id)
    except Exception as e:
        logger.error("letters search failed: %s", e)
        raise HTTPException(502, "Ошибка поиска по письмам") from e
    return [LetterSearchHit(**h.to_dict()) for h in hits]


@router.get("/projects", response_model=list[PayhubProject])
async def projects(
    user: User = Depends(get_current_user),
):
    """Проекты PayHub (реальные названия) для связки с нашими объектами.

    Пустой список, если таблица проектов PayHub не настроена (PAYHUB_PROJECTS_TABLE) —
    экран связки покажет «не настроено». 503 — если весь модуль писем выключен.
    """
    s = get_settings()
    if not s.letters_rag_effective_enabled:
        raise HTTPException(503, "Поиск по письмам PayHub не настроен")
    try:
        return await list_payhub_projects()
    except Exception as e:
        logger.error("payhub projects list failed: %s", e)
        raise HTTPException(502, "Ошибка получения проектов PayHub") from e
