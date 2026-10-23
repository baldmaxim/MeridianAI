"""Схемы документов встречи (Этап 4)."""

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator


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


class DocClassifierItem(BaseModel):
    key: str
    label: str


class DocClassificationVocab(BaseModel):
    doc_types: list[DocClassifierItem]
    doc_tags: list[DocClassifierItem]


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
    # Автоклассификация (None у документов, обработанных до её появления)
    doc_type: str | None = None
    doc_type_label: str | None = None
    doc_tags: list[DocClassifierItem] = []
    doc_meta: dict | None = None

    model_config = {"from_attributes": True}

    @field_validator("doc_tags", mode="before")
    @classmethod
    def _tags_to_items(cls, value):
        # в БД теги лежат списком ключей, наружу — с подписями
        from ..services.document_classify import tag_items
        if value is None:
            return []
        if value and isinstance(value[0], str):
            return tag_items(value)
        return value

    @model_validator(mode="after")
    def _fill_type_label(self):
        from ..services.document_classify import type_label
        if self.doc_type and not self.doc_type_label:
            self.doc_type_label = type_label(self.doc_type)
        return self


class MeetingDocumentItem(BaseModel):
    # id строки meeting_documents; у унаследованного документа без строки — отрицательный (-document_id)
    id: int
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
    # Скан ждёт распознавания: что именно происходит (идёт / компьютер не на связи N ч).
    ocr_note: str | None = None
    # Готовый скан: какие страницы сверить (распознавание могло потерять текст).
    quality_note: str | None = None
    ocr_missing_pages: list[int] = []
    # Откуда документ в контексте встречи: прикреплён к ней / унаследован от заказчика / от объекта
    source: str = "meeting"
    doc_type: str | None = None
    doc_type_label: str | None = None
    doc_tags: list[DocClassifierItem] = []
    doc_meta: dict | None = None


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
