"""Document upload/management API routes."""

import os
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..schemas.meeting import DocumentResponse
from ..auth.dependencies import get_current_user
from sqlalchemy import select, delete as sa_delete

from ..config import get_settings
from ..services.session_manager import get_session_manager
from ..core.context.document_loader import SUPPORTED_EXTENSIONS, DOC_TYPE_LABELS
from ..models.meeting import MeetingDocumentRecord

router = APIRouter()


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(default="other"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document for meeting context."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if not file.filename or ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Поддерживаемые форматы: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    if doc_type not in DOC_TYPE_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid doc_type. Must be one of: {', '.join(DOC_TYPE_LABELS.keys())}",
        )

    settings = get_settings()
    user_upload_dir = os.path.join(settings.upload_dir, str(user.id))
    os.makedirs(user_upload_dir, exist_ok=True)

    # Save file to disk
    file_path = os.path.join(user_upload_dir, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Load into session manager's document loader
    session = get_session_manager(user.id)
    try:
        doc = session.document_loader.load_file(file_path, doc_type)
    except Exception as e:
        # Clean up file on failure
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail=str(e))

    # Persist to DB if linked to a meeting session
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

    return DocumentResponse(
        filename=doc.filename,
        doc_type=doc_type,
        doc_type_label=DOC_TYPE_LABELS.get(doc_type, doc_type),
        page_count=doc.page_count,
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    user: User = Depends(get_current_user),
):
    """List loaded documents for current session."""
    session = get_session_manager(user.id)
    docs = session.document_loader.documents
    return [
        DocumentResponse(
            filename=d.filename,
            doc_type=d.doc_type,
            doc_type_label=DOC_TYPE_LABELS.get(d.doc_type, d.doc_type),
            page_count=d.page_count,
        )
        for d in docs
    ]


@router.delete("/{filename}")
async def remove_document(
    filename: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a loaded document."""
    session = get_session_manager(user.id)
    session.document_loader.remove_document(filename)

    # Remove from DB
    if session.db_session_id:
        await db.execute(
            sa_delete(MeetingDocumentRecord).where(
                MeetingDocumentRecord.session_id == session.db_session_id,
                MeetingDocumentRecord.filename == filename,
            )
        )
        await db.flush()

    # Also remove file from disk
    settings = get_settings()
    file_path = os.path.join(settings.upload_dir, str(user.id), filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    return {"ok": True}
