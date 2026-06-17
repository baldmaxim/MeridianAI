"""Схемы RAG-папок (Этап 5).

path наружу всегда list[str] (в БД хранится как path_json). disabled=True, когда
status == "disabled". Статусы валидируются на create/update в сервисе.
"""

from datetime import datetime

from pydantic import BaseModel

RAG_FOLDER_STATUSES = {"ready", "indexing", "error", "disabled"}


class RagFolderCreate(BaseModel):
    title: str
    description: str | None = None
    customer_id: int | None = None
    object_id: int | None = None
    path: list[str] = []
    status: str = "ready"
    metadata_json: str | None = None


class RagFolderUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    customer_id: int | None = None
    object_id: int | None = None
    path: list[str] | None = None
    status: str | None = None
    metadata_json: str | None = None


class RagFolderOut(BaseModel):
    id: int
    title: str
    description: str | None
    customer_id: int | None
    object_id: int | None
    path: list[str]
    documents_count: int = 0
    chunks_count: int = 0
    updated_at: datetime
    status: str
    status_label: str | None = None
    disabled: bool = False


class RagFolderDocumentAttach(BaseModel):
    document_id: int


class RagFolderDocumentOut(BaseModel):
    id: int
    folder_id: int
    document_id: int
    original_name: str
    file_ext: str | None
    status: str
    chunks_count: int = 0
    created_at: datetime


class RagMeetingFolderAttach(BaseModel):
    folder_id: int
    included: bool = True
    priority: int = 100


class RagMeetingFolderUpdate(BaseModel):
    included: bool | None = None
    priority: int | None = None


class RagAttachedFolderOut(BaseModel):
    source_id: int
    folder_id: int
    title: str
    description: str | None
    path: list[str]
    documents_count: int = 0
    chunks_count: int = 0
    updated_at: datetime
    status: str
    status_label: str | None = None
    disabled: bool = False
    included: bool
    priority: int
