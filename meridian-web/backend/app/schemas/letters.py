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


class LetterSnapshot(BaseModel):
    """Снапшот письма (camelCase — как LetterSearchHit, без score).

    Письма — внешний read-only источник; чтобы прикреплённое письмо детерминированно
    попадало в контекст без обращения к Yandex/pgvector, его поля сохраняются целиком.
    """

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


class MeetingLetterAttach(LetterSnapshot):
    """Тело POST: снапшот письма + флаги включения/приоритета."""

    included: bool = True
    priority: int = 100


class MeetingLetterUpdate(BaseModel):
    included: bool | None = None
    priority: int | None = None


class MeetingLetterOut(LetterSnapshot):
    """Прикреплённое к встрече письмо (для рендера карточки в UI)."""

    sourceId: int
    included: bool
    priority: int
