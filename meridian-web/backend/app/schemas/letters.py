"""Схемы прямого семантического поиска по письмам PayHub (внешний RAG)."""

from pydantic import BaseModel


class LetterSearchRequest(BaseModel):
    query: str
    k: int = 8
    project_id: int | None = None


class LetterSearchHit(BaseModel):
    """Один фрагмент письма (camelCase — как отдаёт RagHit.to_dict)."""

    chunkId: str
    letterId: str | None = None
    subject: str | None = None
    regNumber: str | None = None
    number: str | None = None
    customerNumber: str | None = None
    direction: str | None = None
    letterDate: str | None = None
    projectId: int | None = None
    pageFrom: int | None = None
    pageTo: int | None = None
    text: str
    score: float


class PayhubProject(BaseModel):
    """Проект PayHub для экрана связки «проект PayHub → наш объект» (camelCase)."""

    projectId: int
    name: str
    letterCount: int | None = None
