"""Document API (Этап 4): S3-presigned upload + извлечение текста + чанки.

Новый основной путь — presigned S3 (upload-session → PUT в S3 → confirm-upload → job).
Legacy multipart-загрузка (/upload, /session-docs*) сохранена для обратной совместимости.
"""

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..config import get_settings
from ..models.user import User
from ..models.meeting import MeetingDocumentRecord
from ..models.file import FileRecord
from ..models.document import DocumentRecord, DocumentChunk
from ..models.directory import ProjectObject
from ..auth.dependencies import get_current_user
from ..schemas.meeting import DocumentResponse as LegacyDocumentResponse
from ..schemas.document import (
    DocumentUploadSessionRequest,
    DocumentUploadSessionResponse,
    DocumentConfirmResponse,
    DocumentResponse,
)
from ..services import s3
from ..services.jobs import enqueue
from ..services.access import (
    user_can_access_object,
    user_can_access_document,
    user_can_manage_document,
    accessible_object_ids_select,
)
from ..core.context.document_loader import SUPPORTED_EXTENSIONS, DOC_TYPE_LABELS
from ..services.session_manager import get_session_manager
from ..utils.files import safe_filename

router = APIRouter()


def _chunks_count_subq():
    return (
        select(func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id == DocumentRecord.id)
        .correlate(DocumentRecord)
        .scalar_subquery()
    )


def _to_response(doc: DocumentRecord, chunks_count: int = 0) -> DocumentResponse:
    resp = DocumentResponse.model_validate(doc)
    resp.chunks_count = chunks_count
    return resp


# --- Новый S3-presigned flow ---


@router.post("/upload-session", response_model=DocumentUploadSessionResponse)
async def create_document_upload_session(
    data: DocumentUploadSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    if not settings.s3_enabled:
        raise HTTPException(503, "S3-хранилище не настроено")

    ext = Path(data.filename or "").suffix.lower()
    if ext not in settings.document_allowed_extensions_set:
        raise HTTPException(
            400, f"Формат {ext or '?'} не поддерживается. Допустимые: "
                 f"{', '.join(sorted(settings.document_allowed_extensions_set))}"
        )
    max_bytes = settings.document_max_upload_mb * 1024 * 1024
    if data.size_bytes and data.size_bytes > max_bytes:
        raise HTTPException(400, f"Файл слишком большой (макс. {settings.document_max_upload_mb} МБ)")

    # доступ к объекту + связка customer↔object
    if data.object_id is not None:
        obj = await db.get(ProjectObject, data.object_id)
        if obj is None:
            raise HTTPException(422, "Объект не найден")
        if data.customer_id is not None and obj.customer_id != data.customer_id:
            raise HTTPException(422, "Объект не принадлежит выбранному заказчику")
        if not await user_can_access_object(db, user.id, data.object_id):
            raise HTTPException(403, "Нет доступа к объекту")

    key = s3.object_key(user.id, settings.s3_document_prefix, data.filename)
    file_rec = FileRecord(
        user_id=user.id,
        object_key=key,
        original_name=data.filename or "document",
        size=data.size_bytes,
        mime=data.content_type,
        purpose="document",
        status="pending",
    )
    db.add(file_rec)
    await db.flush()

    doc = DocumentRecord(
        owner_user_id=user.id,
        customer_id=data.customer_id,
        object_id=data.object_id,
        file_id=file_rec.id,
        original_name=data.filename or "document",
        mime_type=data.content_type,
        file_ext=ext,
        file_size=data.size_bytes,
        s3_bucket=settings.s3_bucket,
        s3_key=key,
        status="pending",
        created_by_user_id=user.id,
    )
    db.add(doc)
    await db.flush()

    upload_url = s3.presign_put(key)
    await db.commit()
    return DocumentUploadSessionResponse(
        document_id=doc.id, file_id=file_rec.id, upload_url=upload_url,
        s3_key=key, expires_in=settings.s3_presign_ttl,
    )


@router.post("/{document_id}/confirm-upload", response_model=DocumentConfirmResponse)
async def confirm_document_upload(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(DocumentRecord, document_id)
    if not doc or doc.created_by_user_id != user.id:
        raise HTTPException(404, "Документ не найден")

    meta = await s3.head_object(doc.s3_key)
    if not meta:
        raise HTTPException(400, "Объект не загружен в хранилище")

    doc.status = "uploaded"
    doc.file_size = meta["size"]
    doc.mime_type = meta.get("content_type") or doc.mime_type
    if doc.file_id:
        file_rec = await db.get(FileRecord, doc.file_id)
        if file_rec:
            file_rec.status = "active"
            file_rec.size = meta["size"]
            file_rec.mime = meta.get("content_type")

    await enqueue(db, "document_process", {"document_id": doc.id})
    await db.commit()
    return DocumentConfirmResponse(document_id=doc.id, status=doc.status)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    customer_id: int | None = Query(None),
    object_id: int | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список документов, доступных пользователю (свои + по доступу к объекту)."""
    obj_ids = accessible_object_ids_select(user.id)
    stmt = (
        select(DocumentRecord, _chunks_count_subq().label("chunks_count"))
        .where(
            (DocumentRecord.owner_user_id == user.id)
            | (DocumentRecord.object_id.in_(obj_ids))
        )
        .order_by(DocumentRecord.created_at.desc())
    )
    if customer_id is not None:
        stmt = stmt.where(DocumentRecord.customer_id == customer_id)
    if object_id is not None:
        stmt = stmt.where(DocumentRecord.object_id == object_id)
    if status:
        stmt = stmt.where(DocumentRecord.status == status)
    if q:
        stmt = stmt.where(func.coalesce(DocumentRecord.original_name, "").ilike(f"%{q}%"))
    stmt = stmt.limit(limit).offset(offset)

    rows = (await db.execute(stmt)).all()
    return [_to_response(doc, cc or 0) for doc, cc in rows]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(DocumentRecord, document_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    if not await user_can_access_document(db, user.id, document_id):
        raise HTTPException(403, "Нет доступа к документу")
    cc = await db.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
    )
    return _to_response(doc, cc or 0)


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить документ (создатель/manage-доступ): отвязывает от встреч, чистит чанки,
    физическое удаление файла в S3 — отдельной задачей (§15)."""
    doc = await db.get(DocumentRecord, document_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    if not await user_can_manage_document(db, user.id, document_id):
        raise HTTPException(403, "Недостаточно прав для удаления документа")

    # soft-delete файла + физическое удаление из S3 фоновой задачей
    if doc.file_id:
        file_rec = await db.get(FileRecord, doc.file_id)
        if file_rec and file_rec.status != "deleted":
            file_rec.status = "deleted"
            await enqueue(db, "file_physical_delete", {"object_key": file_rec.object_key})

    # удаление DocumentRecord каскадно снимает chunks и привязки к встречам (FK CASCADE)
    await db.delete(doc)
    await db.commit()
    return {"ok": True}


# --- Legacy multipart flow (DEPRECATED, backward compatibility) ---


@router.post("/upload", response_model=LegacyDocumentResponse, deprecated=True)
async def upload_document_legacy(
    file: UploadFile = File(...),
    doc_type: str = Form(default="other"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """DEPRECATED: multipart-загрузка в in-memory сессию (старый путь до S3)."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if not file.filename or ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Поддерживаемые форматы: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    if doc_type not in DOC_TYPE_LABELS:
        raise HTTPException(400, f"Invalid doc_type: {', '.join(DOC_TYPE_LABELS.keys())}")

    settings = get_settings()
    user_upload_dir = os.path.join(settings.upload_dir, str(user.id))
    os.makedirs(user_upload_dir, exist_ok=True)
    file_path = os.path.join(user_upload_dir, safe_filename(file.filename))
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    session = get_session_manager(user.id)
    try:
        doc = session.document_loader.load_file(file_path, doc_type)
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(400, str(e))

    if session.db_session_id:
        record = MeetingDocumentRecord(
            session_id=session.db_session_id,
            filename=doc.filename,
            doc_type=doc_type,
            page_count=doc.page_count,
            content=doc.content,
        )
        db.add(record)
        await db.flush()

    return LegacyDocumentResponse(
        filename=doc.filename, doc_type=doc_type,
        doc_type_label=DOC_TYPE_LABELS.get(doc_type, doc_type), page_count=doc.page_count,
    )


@router.get("/session-docs", response_model=list[LegacyDocumentResponse], deprecated=True)
async def list_session_documents_legacy(user: User = Depends(get_current_user)):
    """DEPRECATED: документы in-memory сессии."""
    session = get_session_manager(user.id)
    return [
        LegacyDocumentResponse(
            filename=d.filename, doc_type=d.doc_type,
            doc_type_label=DOC_TYPE_LABELS.get(d.doc_type, d.doc_type), page_count=d.page_count,
        )
        for d in session.document_loader.documents
    ]


@router.delete("/session-docs/{filename}", deprecated=True)
async def remove_session_document_legacy(
    filename: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """DEPRECATED: удалить документ из in-memory сессии."""
    session = get_session_manager(user.id)
    session.document_loader.remove_document(filename)
    if session.db_session_id:
        await db.execute(
            sa_delete(MeetingDocumentRecord).where(
                MeetingDocumentRecord.session_id == session.db_session_id,
                MeetingDocumentRecord.filename == filename,
            )
        )
        await db.flush()
    settings = get_settings()
    file_path = os.path.join(settings.upload_dir, str(user.id), safe_filename(filename))
    if os.path.exists(file_path):
        os.remove(file_path)
    return {"ok": True}
