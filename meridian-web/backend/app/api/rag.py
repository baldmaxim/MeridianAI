"""API RAG-папок (Этап 5).

Папки базы знаний (CRUD), привязка существующих документов к папкам и подключение
папок к контексту встречи через meeting_context_sources (source_type='rag_folder').
Доступ — общая модель: list/CRUD папок требуют авторизации; документ — user_can_access_document;
встреча — can_record_meeting (изменение) / user_can_access_meeting (просмотр).

Router монтируется под /api: пути /rag/... и /meetings/{id}/rag-folders.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession
from ..models.document import DocumentRecord
from ..models.context_source import MeetingContextSource
from ..auth.dependencies import get_current_user
from ..services.access import (
    user_can_access_meeting, can_record_meeting, user_can_access_document,
)
from ..services.meeting_room import room_registry
from ..services import rag_context as rag
from ..schemas.rag import (
    RagFolderCreate, RagFolderUpdate, RagFolderOut,
    RagFolderDocumentAttach, RagFolderDocumentOut,
    RagMeetingFolderAttach, RagMeetingFolderUpdate, RagAttachedFolderOut,
)

logger = logging.getLogger("meridian.rag_api")

router = APIRouter()


async def _notify_updated(meeting_id: int) -> None:
    room = room_registry.get_room(meeting_id)
    if room:
        try:
            await room.broadcast({"type": "meeting_context_sources_updated", "meeting_id": meeting_id})
        except Exception:
            pass


async def _get_folder_or_404(db: AsyncSession, folder_id: int):
    folder = await rag.get_rag_folder(db, folder_id)
    if folder is None:
        raise HTTPException(404, "RAG-папка не найдена")
    return folder


# ── папки ─────────────────────────────────────────────────────────────────────

@router.get("/rag/folders", response_model=list[RagFolderOut])
async def list_folders(
    customer_id: int | None = Query(None),
    object_id: int | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await rag.list_rag_folders(
        db, user.id, customer_id=customer_id, object_id=object_id, q=q, limit=limit
    )


@router.post("/rag/folders", response_model=RagFolderOut)
async def create_folder(
    data: RagFolderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await rag.create_rag_folder(db, user.id, data)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/rag/folders/{folder_id}", response_model=RagFolderOut)
async def get_folder(
    folder_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await _get_folder_or_404(db, folder_id)
    return await rag.folder_out(db, folder)


@router.patch("/rag/folders/{folder_id}", response_model=RagFolderOut)
async def update_folder(
    folder_id: int,
    data: RagFolderUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await _get_folder_or_404(db, folder_id)
    try:
        return await rag.update_rag_folder(db, folder, data)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.delete("/rag/folders/{folder_id}")
async def delete_folder(
    folder_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await _get_folder_or_404(db, folder_id)
    await rag.delete_rag_folder(db, folder)
    return {"ok": True}


# ── документы папки ───────────────────────────────────────────────────────────

@router.get("/rag/folders/{folder_id}/documents", response_model=list[RagFolderDocumentOut])
async def list_folder_documents(
    folder_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_folder_or_404(db, folder_id)
    return await rag.list_rag_folder_documents(db, folder_id)


@router.post("/rag/folders/{folder_id}/documents", response_model=RagFolderDocumentOut)
async def attach_folder_document(
    folder_id: int,
    data: RagFolderDocumentAttach,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_folder_or_404(db, folder_id)
    if await db.get(DocumentRecord, data.document_id) is None:
        raise HTTPException(404, "Документ не найден")
    if not await user_can_access_document(db, user.id, data.document_id):
        raise HTTPException(403, "Нет доступа к документу")
    return await rag.attach_document_to_rag_folder(db, folder_id, data.document_id, user.id)


@router.delete("/rag/folders/{folder_id}/documents/{document_id}")
async def detach_folder_document(
    folder_id: int,
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_folder_or_404(db, folder_id)
    await rag.detach_document_from_rag_folder(db, folder_id, document_id)
    return {"ok": True}


# ── подключение папок к встрече ───────────────────────────────────────────────

@router.get("/meetings/{meeting_id}/rag-folders", response_model=list[RagAttachedFolderOut])
async def list_meeting_rag_folders(
    meeting_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    return await rag.list_attached_rag_folders(db, meeting_id, user.id)


@router.post("/meetings/{meeting_id}/rag-folders", response_model=RagAttachedFolderOut)
async def attach_meeting_rag_folder(
    meeting_id: int,
    data: RagMeetingFolderAttach,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(MeetingSession, meeting_id) is None:
        raise HTTPException(404, "Встреча не найдена")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    await _get_folder_or_404(db, data.folder_id)
    try:
        out = await rag.attach_rag_folder_to_meeting(
            db, meeting_id, data.folder_id, user.id,
            included=data.included, priority=data.priority,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    await _notify_updated(meeting_id)
    return out


@router.patch("/meetings/{meeting_id}/rag-folders/{source_id}", response_model=RagAttachedFolderOut)
async def update_meeting_rag_folder(
    meeting_id: int,
    source_id: int,
    data: RagMeetingFolderUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    src = await db.get(MeetingContextSource, source_id)
    if not src or src.meeting_id != meeting_id or src.source_type != rag.SOURCE_TYPE_RAG_FOLDER:
        raise HTTPException(404, "RAG-папка не подключена")
    try:
        out = await rag.update_attached_rag_folder(db, src, included=data.included, priority=data.priority)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await _notify_updated(meeting_id)
    return out


@router.delete("/meetings/{meeting_id}/rag-folders/{source_id}")
async def detach_meeting_rag_folder(
    meeting_id: int,
    source_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения контекста встречи")
    src = await db.get(MeetingContextSource, source_id)
    if not src or src.meeting_id != meeting_id or src.source_type != rag.SOURCE_TYPE_RAG_FOLDER:
        raise HTTPException(404, "RAG-папка не подключена")
    await rag.detach_rag_folder_from_meeting(db, src)
    await _notify_updated(meeting_id)
    return {"ok": True}
