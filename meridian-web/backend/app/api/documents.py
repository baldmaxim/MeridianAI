"""Document API (Этап 4): S3-presigned upload + извлечение текста + чанки.

Новый основной путь — presigned S3 (upload-session → PUT в S3 → confirm-upload → job).
Legacy multipart-загрузка (/upload, /session-docs*) сохранена для обратной совместимости.
"""

import logging
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Response
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
from ..services import document_storage
from ..services.jobs import enqueue

logger = logging.getLogger("meridian.documents")


def _safe_ct(content_type: str | None) -> str:
    """Content-type для лога: не PII, но обрезаем и схлопываем пробелы (защита от мусора)."""
    return " ".join(str(content_type or "-").split())[:80]
from ..services.access import (
    user_can_access_object,
    user_can_access_document,
    user_can_manage_document,
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
    response: Response = None,  # FastAPI инжектит реальный Response; None только при прямом вызове в тестах
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    # ответ содержит presigned URL (AWS-подпись в query) → запрещаем кэширование (браузер/прокси/HAR)
    if response is not None:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    # Этап 22: S3 выключен/kill-switch → отдаём mode=legacy_multipart (без 503), фронт грузит
    # через /api/documents/upload. Так dev/local и misconfigured прод не ломаются.
    if not document_storage.is_enabled():
        # Этап 23: безопасный маркер для log-анализатора (только user_id, без PII/URL/ключей)
        logger.info("[DocumentS3Upload] legacy_fallback user_id=%s", user.id)
        return DocumentUploadSessionResponse(
            upload_mode="legacy_multipart",
            legacy_upload_url="/api/documents/upload",
            max_upload_bytes=settings.document_max_upload_mb * 1024 * 1024,
        )

    try:
        ext = document_storage.validate_upload(data.filename, data.content_type, data.size_bytes)
    except document_storage.DocumentStorageError as e:
        raise HTTPException(400, str(e))

    # доступ к объекту + связка customer↔object
    if data.object_id is not None:
        obj = await db.get(ProjectObject, data.object_id)
        if obj is None:
            raise HTTPException(422, "Объект не найден")
        if data.customer_id is not None and obj.customer_id != data.customer_id:
            raise HTTPException(422, "Объект не принадлежит выбранному заказчику")
        if not await user_can_access_object(db, user.id, data.object_id):
            raise HTTPException(403, "Нет доступа к объекту")

    key = document_storage.build_object_key(user.id, data.filename)
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

    upload_url, headers = document_storage.create_presigned_put(key, data.content_type)
    await db.commit()
    # безопасный лог: без filename/URL/token/bucket-key (только тех.метаданные + hash-ref)
    logger.info("[DocumentS3Upload] initiated user_id=%s meeting_id=%s content_type=%s size=%s ext=%s ref=%s",
                user.id, None, _safe_ct(data.content_type), data.size_bytes or 0, ext,
                document_storage.safe_storage_ref(key))
    return DocumentUploadSessionResponse(
        upload_mode="s3_presigned",
        document_id=doc.id, file_id=file_rec.id, upload_url=upload_url,
        s3_key=key, expires_in=document_storage.presign_expires(),
        headers=headers, max_upload_bytes=document_storage.max_upload_bytes(),
    )


@router.post("/{document_id}/confirm-upload", response_model=DocumentConfirmResponse)
async def confirm_document_upload(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    doc = await db.get(DocumentRecord, document_id)
    if not doc or doc.created_by_user_id != user.id:
        raise HTTPException(404, "Документ не найден")

    # HEAD-проверка (Этап 22): при наличии метаданных размер (≥0, ≤лимита) и content-type
    # валидируются ВСЕГДА (спека: content-type/размер и на confirm). Флаг
    # DOCUMENT_S3_COMPLETE_HEAD_CHECK_ENABLED лишь смягчает случай отсутствующего HEAD
    # (eventual-consistent хранилище): при выключенном флаге допускаем meta=None.
    meta = await document_storage.head_object(doc.s3_key)
    if meta is not None:
        try:
            document_storage.validate_head(meta)
        except document_storage.DocumentStorageError as e:
            raise HTTPException(400, str(e))
    elif settings.document_s3_complete_head_check_enabled:
        raise HTTPException(400, "Объект не загружен в хранилище")

    doc.status = "uploaded"
    if meta:
        doc.file_size = meta["size"]
        doc.mime_type = meta.get("content_type") or doc.mime_type
    if doc.file_id:
        file_rec = await db.get(FileRecord, doc.file_id)
        if file_rec:
            file_rec.status = "active"
            if meta:
                file_rec.size = meta["size"]
                file_rec.mime = meta.get("content_type")

    await enqueue(db, "document_process", {"document_id": doc.id})
    await db.commit()
    logger.info("[DocumentS3Upload] completed user_id=%s meeting_id=%s size=%s ext=%s ref=%s",
                user.id, None, doc.file_size or 0, doc.file_ext,
                document_storage.safe_storage_ref(doc.s3_key))
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
    """Список документов (общая хронология — видны все)."""
    stmt = (
        select(DocumentRecord, _chunks_count_subq().label("chunks_count"))
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
