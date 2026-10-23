"""Документы встречи: прикреплённые + унаследованные от заказчика/объекта.

Общая логика для сайта (api/history.py) и десктоп-приложения (api/desktop.py).

Унаследованный документ не имеет строки meeting_documents, пока пользователь его не тронул.
Тронул (выключил, убрал, поменял приоритет) — создаётся «строка-переопределение»: она отличается
от явного прикрепления пустым added_by_user_id. Сам список того, что уходит в подсказки, считает
document_context.effective_meeting_document_ids.
"""

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.document import DocumentChunk, DocumentRecord
from ..models.meeting import MeetingDocumentRecord, MeetingSession
from ..schemas.document import MeetingDocumentItem
from .document_classify import tag_items, type_label
from .document_context import DEFAULT_DOCUMENT_PRIORITY, inherited_documents_stmt

SOURCE_MEETING = "meeting"
SOURCE_CUSTOMER = "customer"
SOURCE_OBJECT = "object"


def inherited_source(meeting: MeetingSession, doc: DocumentRecord) -> str | None:
    """«customer» / «object», если документ наследуется встречей; иначе None."""
    if meeting.customer_id is not None and doc.customer_id == meeting.customer_id:
        return SOURCE_CUSTOMER
    if meeting.object_id is not None and doc.object_id == meeting.object_id:
        return SOURCE_OBJECT
    return None


def _ocr_warnings(doc: DocumentRecord) -> list[dict]:
    try:
        warnings = json.loads(doc.summary_json or "{}").get("ocr_warnings") or []
    except (ValueError, AttributeError):
        return []
    return [w for w in warnings if isinstance(w, dict) and isinstance(w.get("page"), int)]


def meeting_doc_item(
    md: MeetingDocumentRecord | None, doc: DocumentRecord, chunks_count: int,
    ocr_note: str | None = None, *, source: str = SOURCE_MEETING,
) -> MeetingDocumentItem:
    from .ocr_quality import ocr_quality_note
    warnings = _ocr_warnings(doc) if doc.status == "ready" else []
    return MeetingDocumentItem(
        # у унаследованного документа без строки id отрицательный: уникален и не пересекается со строками
        id=md.id if md is not None else -doc.id,
        document_id=doc.id,
        original_name=doc.original_name,
        file_ext=doc.file_ext,
        status=doc.status,
        included=md.included if md is not None else True,
        priority=md.priority if md is not None else DEFAULT_DOCUMENT_PRIORITY,
        chunks_count=chunks_count,
        page_count=doc.page_count,
        sheet_count=doc.sheet_count,
        processing_error=doc.processing_error,
        ocr_note=ocr_note,
        quality_note=ocr_quality_note(warnings),
        ocr_missing_pages=sorted(w["page"] for w in warnings if w.get("reason") == "страница не распознана"),
        source=source,
        doc_type=doc.doc_type,
        doc_type_label=type_label(doc.doc_type),
        doc_tags=tag_items(doc.doc_tags),
        doc_meta=doc.doc_meta,
    )


def _chunks_count_subq():
    return (
        select(func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id == DocumentRecord.id)
        .correlate(DocumentRecord)
        .scalar_subquery()
    )


async def _chunks_count(db: AsyncSession, document_id: int) -> int:
    return await db.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
    ) or 0


async def get_meeting_document_row(
    db: AsyncSession, meeting_id: int, document_id: int,
) -> MeetingDocumentRecord | None:
    return (
        await db.execute(
            select(MeetingDocumentRecord).where(
                MeetingDocumentRecord.session_id == meeting_id,
                MeetingDocumentRecord.document_id == document_id,
            )
        )
    ).scalar_one_or_none()


async def list_meeting_document_items(db: AsyncSession, meeting: MeetingSession) -> list[MeetingDocumentItem]:
    """Прикреплённые документы встречи + готовые документы её заказчика/объекта."""
    from .ocr_queue import ocr_waiting_notes
    chunks_subq = _chunks_count_subq()
    rows = (
        await db.execute(
            select(MeetingDocumentRecord, DocumentRecord, chunks_subq.label("chunks_count"))
            .join(DocumentRecord, DocumentRecord.id == MeetingDocumentRecord.document_id)
            .where(
                MeetingDocumentRecord.session_id == meeting.id,
                MeetingDocumentRecord.document_id.isnot(None),
            )
            .order_by(MeetingDocumentRecord.priority.desc(), MeetingDocumentRecord.id)
        )
    ).all()

    inherited_rows: list = []
    inherited = inherited_documents_stmt(meeting)
    if inherited is not None:
        attached_ids = {doc.id for _, doc, _ in rows}
        inherited_rows = [
            (doc, cc) for doc, cc in (
                await db.execute(
                    select(DocumentRecord, chunks_subq.label("chunks_count"))
                    .where(DocumentRecord.id.in_(inherited))
                    .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
                )
            ).all()
            if doc.id not in attached_ids
        ]

    # ждёт распознавания целиком — или готов, но пустые страницы досдаются агентом
    all_docs = [doc for _, doc, _ in rows] + [doc for doc, _ in inherited_rows]
    notes = await ocr_waiting_notes(
        db, [d.id for d in all_docs if d.status == "awaiting_ocr" or _ocr_warnings(d)]
    )

    items: list[MeetingDocumentItem] = []
    for md, doc, cc in rows:
        source = SOURCE_MEETING
        if md.added_by_user_id is None:  # строка-переопределение унаследованного документа
            source = inherited_source(meeting, doc) or SOURCE_MEETING
        items.append(meeting_doc_item(md, doc, cc or 0, notes.get(doc.id), source=source))
    for doc, cc in inherited_rows:
        items.append(meeting_doc_item(
            None, doc, cc or 0, notes.get(doc.id), source=inherited_source(meeting, doc) or SOURCE_MEETING,
        ))
    return items


def _new_row(
    meeting: MeetingSession, doc: DocumentRecord, *, included: bool, added_by_user_id: int | None,
    priority: int = DEFAULT_DOCUMENT_PRIORITY,
) -> MeetingDocumentRecord:
    return MeetingDocumentRecord(
        session_id=meeting.id,
        document_id=doc.id,
        added_by_user_id=added_by_user_id,
        filename=doc.original_name,
        doc_type=doc.file_ext,
        page_count=doc.page_count or 1,
        priority=priority,
        included=included,
    )


async def attach_document(
    db: AsyncSession, meeting: MeetingSession, doc: DocumentRecord, user_id: int,
) -> MeetingDocumentRecord:
    """Прикрепить документ к встрече. Повтор безопасен (идемпотентно)."""
    row = await get_meeting_document_row(db, meeting.id, doc.id)
    if row is None:
        row = _new_row(meeting, doc, included=True, added_by_user_id=user_id)
        db.add(row)
    elif row.added_by_user_id is None:
        # документ был унаследован и скрыт/тронут — явное прикрепление возвращает его в контекст
        row.added_by_user_id = user_id
        row.included = True
    await db.flush()
    await db.refresh(row)
    return row


async def set_document_inclusion(
    db: AsyncSession, meeting: MeetingSession, document_id: int, *,
    included: bool | None, priority: int | None,
) -> tuple[MeetingDocumentRecord, DocumentRecord] | None:
    """Включить/выключить документ или сменить приоритет. Для унаследованного документа
    без строки строка создаётся. None — документ не прикреплён и не унаследован."""
    doc = await db.get(DocumentRecord, document_id)
    if doc is None:
        return None
    row = await get_meeting_document_row(db, meeting.id, document_id)
    if row is None:
        if inherited_source(meeting, doc) is None:
            return None
        row = _new_row(meeting, doc, included=True, added_by_user_id=None)
        db.add(row)
    if included is not None:
        row.included = included
    if priority is not None:
        row.priority = priority
    await db.flush()
    await db.refresh(row)
    return row, doc


async def detach_document(db: AsyncSession, meeting: MeetingSession, document_id: int) -> bool:
    """Убрать документ из встречи. Документ заказчика/объекта нельзя «открепить» совсем —
    он скрывается строкой included=false. False — документа в этой встрече нет."""
    doc = await db.get(DocumentRecord, document_id)
    row = await get_meeting_document_row(db, meeting.id, document_id)
    inherits = doc is not None and inherited_source(meeting, doc) is not None
    if row is None:
        if not inherits:
            return False
        db.add(_new_row(meeting, doc, included=False, added_by_user_id=None))
    elif inherits:
        row.included = False
        row.added_by_user_id = None
    else:
        await db.delete(row)
    await db.flush()
    return True


async def meeting_document_item(
    db: AsyncSession, meeting: MeetingSession, md: MeetingDocumentRecord, doc: DocumentRecord,
) -> MeetingDocumentItem:
    source = SOURCE_MEETING
    if md.added_by_user_id is None:
        source = inherited_source(meeting, doc) or SOURCE_MEETING
    return meeting_doc_item(md, doc, await _chunks_count(db, doc.id), source=source)
