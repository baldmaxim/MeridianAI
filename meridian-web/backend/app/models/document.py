"""Документы встречи на S3 + извлечённые чанки (Этап 4).

DocumentRecord — метаданные документа (оригинал в S3 через FileRecord).
DocumentChunk — извлечённый текст, разбитый на фрагменты, для retrieval в LLM-подсказках.
Scope — owner_user_id (seam под будущий organization_id; см. CLAUDE.md).
"""

from datetime import datetime

from sqlalchemy import (
    String,
    Text,
    Boolean,
    DateTime,
    Integer,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class DocumentRecord(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # owner_user_id/created_by_user_id — метки автора, не ключ доступа.
    # SET NULL: документ переживает удаление пользователя.
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    customer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="SET NULL")
    )
    object_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("project_objects.id", ondelete="SET NULL")
    )
    file_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("files.id", ondelete="SET NULL")
    )
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_ext: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer)
    s3_bucket: Mapped[str | None] = mapped_column(String(200))
    s3_key: Mapped[str | None] = mapped_column(String(500))
    # pending | uploaded | processing | ready | error
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    processing_error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    sheet_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text_s3_key: Mapped[str | None] = mapped_column(String(500))
    summary_json: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_documents_owner", "owner_user_id"),
        Index("ix_documents_customer", "customer_id"),
        Index("ix_documents_object", "object_id"),
        Index("ix_documents_status", "status"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(200))
    section_title: Mapped[str | None] = mapped_column(String(300))
    token_count: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_document_chunks_doc", "document_id", "chunk_index"),
    )
