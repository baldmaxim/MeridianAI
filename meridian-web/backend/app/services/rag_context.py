"""RagContextService (Этап 5): RAG-папки и их подключение к контексту встречи.

Управление: папки (CRUD), привязка существующих документов к папкам, подключение
папок к встрече через meeting_context_sources (source_type='rag_folder').

Retrieval v1 — лексический keyword-scoring по DocumentChunk (как document_context.py).
Готово к замене на embeddings/vector search: интерфейс get_relevant_rag_chunks_for_meeting()
и build_meeting_rag_context() стабильны, меняется только реализация scoring.

Бизнес-валидации бросают ValueError (API → 422). Существование/доступ проверяет API-слой.
"""

import json
import logging
import re

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import async_session
from ..models.rag import RagFolder, RagFolderDocument
from ..models.document import DocumentRecord, DocumentChunk
from ..models.context_source import MeetingContextSource
from ..models.directory import Customer, ProjectObject
from ..schemas.rag import (
    RAG_FOLDER_STATUSES, RagFolderCreate, RagFolderUpdate, RagFolderOut,
    RagFolderDocumentOut, RagAttachedFolderOut,
)

logger = logging.getLogger("meridian.rag")

SOURCE_TYPE_RAG_FOLDER = "rag_folder"

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)

_STATUS_LABELS = {
    "ready": "готова",
    "indexing": "индексация",
    "error": "ошибка",
    "disabled": "отключена",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 3}


def _parse_path(path_json: str | None) -> list[str]:
    if not path_json:
        return []
    try:
        value = json.loads(path_json)
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    return [str(x) for x in value]


def _dump_path(path: list[str] | None) -> str | None:
    if not path:
        return None
    try:
        return json.dumps([str(x) for x in path], ensure_ascii=False)
    except Exception:
        return None


def _folder_status_label(folder: RagFolder, docs_stats: tuple[int, int]) -> str | None:
    return _STATUS_LABELS.get(folder.status)


async def _folder_doc_stats(db: AsyncSession, folder_ids: list[int]) -> dict[int, tuple[int, int]]:
    """{folder_id: (documents_count, chunks_count)} одним запросом."""
    if not folder_ids:
        return {}
    rows = (await db.execute(
        select(
            RagFolderDocument.folder_id,
            func.count(func.distinct(RagFolderDocument.document_id)),
            func.count(DocumentChunk.id),
        )
        .select_from(RagFolderDocument)
        .join(DocumentRecord, DocumentRecord.id == RagFolderDocument.document_id)
        .outerjoin(DocumentChunk, DocumentChunk.document_id == DocumentRecord.id)
        .where(RagFolderDocument.folder_id.in_(folder_ids))
        .group_by(RagFolderDocument.folder_id)
    )).all()
    return {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in rows}


async def _chunk_counts(db: AsyncSession, doc_ids: list[int]) -> dict[int, int]:
    if not doc_ids:
        return {}
    rows = (await db.execute(
        select(DocumentChunk.document_id, func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id.in_(doc_ids))
        .group_by(DocumentChunk.document_id)
    )).all()
    return {r[0]: int(r[1] or 0) for r in rows}


def _folder_to_out(folder: RagFolder, stats: tuple[int, int]) -> RagFolderOut:
    docs, chunks = stats
    return RagFolderOut(
        id=folder.id, title=folder.title, description=folder.description,
        customer_id=folder.customer_id, object_id=folder.object_id,
        path=_parse_path(folder.path_json),
        documents_count=docs, chunks_count=chunks,
        updated_at=folder.updated_at, status=folder.status,
        status_label=_folder_status_label(folder, stats),
        disabled=(folder.status == "disabled"),
    )


def _attached_to_out(folder: RagFolder, src: MeetingContextSource, stats: tuple[int, int]) -> RagAttachedFolderOut:
    docs, chunks = stats
    return RagAttachedFolderOut(
        source_id=src.id, folder_id=folder.id, title=folder.title, description=folder.description,
        path=_parse_path(folder.path_json), documents_count=docs, chunks_count=chunks,
        updated_at=folder.updated_at, status=folder.status,
        status_label=_folder_status_label(folder, stats), disabled=(folder.status == "disabled"),
        included=src.included, priority=src.priority,
    )


# ── папки (CRUD) ──────────────────────────────────────────────────────────────

async def get_rag_folder(db: AsyncSession, folder_id: int) -> RagFolder | None:
    return await db.get(RagFolder, folder_id)


async def folder_out(db: AsyncSession, folder: RagFolder) -> RagFolderOut:
    """RagFolderOut с актуальными counts для одной папки."""
    stats = await _folder_doc_stats(db, [folder.id])
    return _folder_to_out(folder, stats.get(folder.id, (0, 0)))


async def list_rag_folders(
    db: AsyncSession,
    user_id: int,
    customer_id: int | None = None,
    object_id: int | None = None,
    q: str | None = None,
    limit: int = 50,
) -> list[RagFolderOut]:
    limit = min(max(limit, 1), 100)
    stmt = select(RagFolder)
    if customer_id is not None or object_id is not None:
        ors = [and_(RagFolder.customer_id.is_(None), RagFolder.object_id.is_(None))]
        if customer_id is not None:
            ors.append(and_(RagFolder.customer_id == customer_id, RagFolder.object_id.is_(None)))
        if object_id is not None:
            ors.append(RagFolder.object_id == object_id)
        stmt = stmt.where(or_(*ors))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(RagFolder.title.ilike(like), RagFolder.description.ilike(like)))
    stmt = stmt.order_by(RagFolder.updated_at.desc()).limit(limit)
    folders = (await db.execute(stmt)).scalars().all()
    stats = await _folder_doc_stats(db, [f.id for f in folders])
    return [_folder_to_out(f, stats.get(f.id, (0, 0))) for f in folders]


async def create_rag_folder(db: AsyncSession, user_id: int, data: RagFolderCreate) -> RagFolderOut:
    title = (data.title or "").strip()
    if not title:
        raise ValueError("Название RAG-папки обязательно")
    if data.status not in RAG_FOLDER_STATUSES:
        raise ValueError("Недопустимый статус RAG-папки")
    if data.customer_id is not None and await db.get(Customer, data.customer_id) is None:
        raise ValueError("Заказчик не найден")
    if data.object_id is not None and await db.get(ProjectObject, data.object_id) is None:
        raise ValueError("Объект не найден")
    folder = RagFolder(
        owner_user_id=user_id, customer_id=data.customer_id, object_id=data.object_id,
        title=title, description=data.description, path_json=_dump_path(data.path),
        status=data.status, metadata_json=data.metadata_json, created_by_user_id=user_id,
    )
    db.add(folder)
    await db.flush()
    await db.refresh(folder)
    return _folder_to_out(folder, (0, 0))


async def update_rag_folder(db: AsyncSession, folder: RagFolder, data: RagFolderUpdate) -> RagFolderOut:
    updates = data.model_dump(exclude_unset=True)
    if updates.get("status") is not None and updates["status"] not in RAG_FOLDER_STATUSES:
        raise ValueError("Недопустимый статус RAG-папки")
    if "title" in updates and updates["title"] is not None:
        t = updates.pop("title").strip()
        if not t:
            raise ValueError("Название RAG-папки обязательно")
        folder.title = t
    if updates.get("customer_id") is not None and await db.get(Customer, updates["customer_id"]) is None:
        raise ValueError("Заказчик не найден")
    if updates.get("object_id") is not None and await db.get(ProjectObject, updates["object_id"]) is None:
        raise ValueError("Объект не найден")
    if "path" in updates:
        folder.path_json = _dump_path(updates.pop("path"))
    for key, value in updates.items():
        setattr(folder, key, value)
    await db.flush()
    await db.refresh(folder)
    stats = await _folder_doc_stats(db, [folder.id])
    return _folder_to_out(folder, stats.get(folder.id, (0, 0)))


async def delete_rag_folder(db: AsyncSession, folder: RagFolder) -> None:
    await db.delete(folder)
    await db.flush()


# ── документы папки ───────────────────────────────────────────────────────────

async def list_rag_folder_documents(db: AsyncSession, folder_id: int) -> list[RagFolderDocumentOut]:
    rows = (await db.execute(
        select(RagFolderDocument, DocumentRecord)
        .join(DocumentRecord, DocumentRecord.id == RagFolderDocument.document_id)
        .where(RagFolderDocument.folder_id == folder_id)
        .order_by(RagFolderDocument.created_at.asc())
    )).all()
    if not rows:
        return []
    counts = await _chunk_counts(db, [doc.id for _, doc in rows])
    return [
        RagFolderDocumentOut(
            id=link.id, folder_id=link.folder_id, document_id=doc.id,
            original_name=doc.original_name, file_ext=doc.file_ext, status=doc.status,
            chunks_count=counts.get(doc.id, 0), created_at=link.created_at,
        )
        for link, doc in rows
    ]


async def attach_document_to_rag_folder(
    db: AsyncSession, folder_id: int, document_id: int, user_id: int,
) -> RagFolderDocumentOut:
    existing = (await db.execute(
        select(RagFolderDocument).where(
            RagFolderDocument.folder_id == folder_id,
            RagFolderDocument.document_id == document_id,
        )
    )).scalar_one_or_none()
    if existing is None:
        existing = RagFolderDocument(folder_id=folder_id, document_id=document_id, added_by_user_id=user_id)
        db.add(existing)
        await db.flush()
        await db.refresh(existing)
    doc = await db.get(DocumentRecord, document_id)
    counts = await _chunk_counts(db, [document_id])
    return RagFolderDocumentOut(
        id=existing.id, folder_id=folder_id, document_id=document_id,
        original_name=doc.original_name, file_ext=doc.file_ext, status=doc.status,
        chunks_count=counts.get(document_id, 0), created_at=existing.created_at,
    )


async def detach_document_from_rag_folder(db: AsyncSession, folder_id: int, document_id: int) -> None:
    link = (await db.execute(
        select(RagFolderDocument).where(
            RagFolderDocument.folder_id == folder_id,
            RagFolderDocument.document_id == document_id,
        )
    )).scalar_one_or_none()
    if link is not None:
        await db.delete(link)
        await db.flush()


# ── подключение папок к встрече ───────────────────────────────────────────────

async def list_attached_rag_folders(
    db: AsyncSession, meeting_id: int, user_id: int,
) -> list[RagAttachedFolderOut]:
    srcs = (await db.execute(
        select(MeetingContextSource).where(
            MeetingContextSource.meeting_id == meeting_id,
            MeetingContextSource.source_type == SOURCE_TYPE_RAG_FOLDER,
            MeetingContextSource.source_id.isnot(None),
        ).order_by(MeetingContextSource.priority.asc(), MeetingContextSource.created_at.asc())
    )).scalars().all()
    folder_ids = [s.source_id for s in srcs]
    folders = {}
    if folder_ids:
        folders = {
            f.id: f for f in (await db.execute(
                select(RagFolder).where(RagFolder.id.in_(folder_ids))
            )).scalars().all()
        }
    stats = await _folder_doc_stats(db, list(folders.keys()))
    out: list[RagAttachedFolderOut] = []
    for s in srcs:
        folder = folders.get(s.source_id)
        if folder is None:
            continue  # папка удалена — не падаем, просто пропускаем
        out.append(_attached_to_out(folder, s, stats.get(folder.id, (0, 0))))
    return out


async def attach_rag_folder_to_meeting(
    db: AsyncSession, meeting_id: int, folder_id: int, user_id: int,
    included: bool = True, priority: int = 100,
) -> RagAttachedFolderOut:
    folder = await db.get(RagFolder, folder_id)
    if folder is None:
        raise ValueError("RAG-папка не найдена")
    if folder.status == "disabled":
        raise ValueError("RAG-папка отключена")
    existing = (await db.execute(
        select(MeetingContextSource).where(
            MeetingContextSource.meeting_id == meeting_id,
            MeetingContextSource.source_type == SOURCE_TYPE_RAG_FOLDER,
            MeetingContextSource.source_id == folder_id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        existing.included = included
        existing.priority = priority
        src = existing
    else:
        src = MeetingContextSource(
            meeting_id=meeting_id, source_type=SOURCE_TYPE_RAG_FOLDER, source_id=folder_id,
            included=included, priority=priority, added_by_user_id=user_id,
            metadata_json=json.dumps({"folder_title": folder.title}, ensure_ascii=False),
        )
        db.add(src)
    await db.flush()
    await db.refresh(src)
    stats = await _folder_doc_stats(db, [folder.id])
    return _attached_to_out(folder, src, stats.get(folder.id, (0, 0)))


async def update_attached_rag_folder(
    db: AsyncSession, src: MeetingContextSource,
    included: bool | None = None, priority: int | None = None,
) -> RagAttachedFolderOut:
    if included is not None:
        src.included = included
    if priority is not None:
        src.priority = priority
    await db.flush()
    await db.refresh(src)
    folder = await db.get(RagFolder, src.source_id)
    if folder is None:
        raise ValueError("RAG-папка не найдена")
    stats = await _folder_doc_stats(db, [folder.id])
    return _attached_to_out(folder, src, stats.get(folder.id, (0, 0)))


async def detach_rag_folder_from_meeting(db: AsyncSession, src: MeetingContextSource) -> None:
    await db.delete(src)
    await db.flush()


# ── retrieval provider ────────────────────────────────────────────────────────

async def get_relevant_rag_chunks_for_meeting(
    db: AsyncSession, meeting_id: int, query_text: str, limit: int = 8,
) -> list[dict]:
    """Top-N релевантных чанков среди included RAG-папок встречи.

    included MeetingContextSource(rag_folder) → RagFolderDocument → DocumentRecord(ready)
    → DocumentChunk. folder.status должен быть ready|indexing (disabled/error исключены).
    """
    rows = (await db.execute(
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.text,
            DocumentChunk.page_number,
            DocumentChunk.sheet_name,
            DocumentRecord.original_name,
            RagFolder.id.label("folder_id"),
            RagFolder.title.label("folder_title"),
            MeetingContextSource.priority,
        )
        .select_from(MeetingContextSource)
        .join(RagFolder, RagFolder.id == MeetingContextSource.source_id)
        .join(RagFolderDocument, RagFolderDocument.folder_id == RagFolder.id)
        .join(DocumentRecord, DocumentRecord.id == RagFolderDocument.document_id)
        .join(DocumentChunk, DocumentChunk.document_id == DocumentRecord.id)
        .where(
            MeetingContextSource.meeting_id == meeting_id,
            MeetingContextSource.source_type == SOURCE_TYPE_RAG_FOLDER,
            MeetingContextSource.included == True,  # noqa: E712
            MeetingContextSource.source_id.isnot(None),
            DocumentRecord.status == "ready",
            RagFolder.status.in_(["ready", "indexing"]),
        )
    )).all()
    if not rows:
        return []

    q = _tokens(query_text)
    ql = (query_text or "").lower()
    scored: list[tuple[float, object]] = []
    for r in rows:
        priority_boost = (r.priority or 100) / 100000.0
        if not q:
            score = priority_boost - r.chunk_index / 1_000_000.0
        else:
            overlap = len(q & _tokens(r.text))
            if overlap == 0:
                continue
            score = overlap / len(q) + priority_boost
            if len(ql) >= 6 and ql[:40] in r.text.lower():
                score += 0.2
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for score, r in scored[:limit]:
        out.append({
            "folder_id": r.folder_id,
            "folder_title": r.folder_title,
            "document_id": r.document_id,
            "document_name": r.original_name,
            "chunk_id": r.id,
            "text": r.text,
            "page_number": r.page_number,
            "sheet_name": r.sheet_name,
            "score": round(float(score), 4),
        })
    return out


def format_rag_chunks_block(chunks: list[dict], max_chunks: int, max_chars: int) -> str:
    """Промпт-блок 'Релевантные фрагменты RAG-папок:' с лимитами."""
    if not chunks:
        return ""
    parts: list[str] = []
    total = 0
    for c in chunks[:max_chunks]:
        loc = ""
        if c.get("page_number"):
            loc = f" | Страница {c['page_number']}"
        elif c.get("sheet_name"):
            loc = f" | Лист: {c['sheet_name']}"
        header = f"[RAG-папка: {c['folder_title']} | Документ: {c['document_name']}{loc}]"
        text = c["text"]
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining < 200:
                break
            text = text[:remaining].rstrip() + "…"
        parts.append(f"{header}\n{text}")
        total += len(text)
        if total >= max_chars:
            break
    if not parts:
        return ""
    return "Релевантные фрагменты RAG-папок:\n\n" + "\n\n".join(parts)


async def build_meeting_rag_context(meeting_id: int, query_text: str = "") -> str:
    """Провайдер для SessionManager: готовый промпт-блок RAG-папок (или '').

    Открывает собственную сессию БД (вызывается из STT/LLM-движка). Никогда не падает.
    """
    settings = get_settings()
    if not settings.rag_context_enabled:
        return ""
    try:
        async with async_session() as db:
            chunks = await get_relevant_rag_chunks_for_meeting(
                db, meeting_id, query_text, limit=settings.rag_context_max_chunks
            )
        return format_rag_chunks_block(
            chunks, settings.rag_context_max_chunks, settings.rag_context_max_chars
        )
    except Exception as e:
        logger.error("rag context build failed for meeting %s: %s", meeting_id, e)
        return ""
