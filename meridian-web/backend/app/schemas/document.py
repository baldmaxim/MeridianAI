"""Схемы документов встречи (Этап 4)."""

from datetime import datetime

from pydantic import BaseModel


class DocumentUploadSessionRequest(BaseModel):
    filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    customer_id: int | None = None
    object_id: int | None = None


class DocumentUploadSessionResponse(BaseModel):
    # Этап 22: mode-aware. s3_presigned → поля upload_url/headers заполнены; legacy_multipart →
    # только upload_mode + legacy_upload_url (dev/local/kill-switch fallback на /api/documents/upload).
    upload_mode: str = "s3_presigned"
    document_id: int | None = None
    file_id: int | None = None
    upload_url: str | None = None
    s3_key: str | None = None
    expires_in: int | None = None
    headers: dict[str, str] = {}
    max_upload_bytes: int | None = None
    legacy_upload_url: str | None = None


class DocumentConfirmResponse(BaseModel):
    document_id: int
    status: str


class DocumentResponse(BaseModel):
    id: int
    owner_user_id: int
    customer_id: int | None
    object_id: int | None
    file_id: int | None
    original_name: str
    mime_type: str | None
    file_ext: str
    file_size: int | None
    status: str
    processing_error: str | None
    page_count: int | None
    sheet_count: int | None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime
    chunks_count: int = 0

    model_config = {"from_attributes": True}


class MeetingDocumentItem(BaseModel):
    id: int  # id строки meeting_documents
    document_id: int
    original_name: str
    file_ext: str | None
    status: str
    included: bool
    priority: int
    chunks_count: int
    page_count: int | None
    sheet_count: int | None
    processing_error: str | None


class MeetingDocumentPatch(BaseModel):
    included: bool | None = None
    priority: int | None = None


class RelevantDocumentChunk(BaseModel):
    document_id: int
    document_name: str
    chunk_id: int
    text: str
    page_number: int | None
    sheet_name: str | None
    score: float
