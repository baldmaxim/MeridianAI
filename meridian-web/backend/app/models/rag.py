"""RAG-папки (Этап 5): группировка существующих документов в именованные папки
базы знаний и подключение их к контексту встречи.

RagFolder — папка (global / customer-scoped / object-scoped по аналогии с документами).
RagFolderDocument — связь папка↔документ (документы остаются в DocumentRecord).
Подключение папки к встрече хранится в meeting_context_sources (source_type='rag_folder',
source_id=rag_folders.id) — отдельной таблицы для этого нет.

Retrieval v1 — лексический scoring по DocumentChunk (как document_context.py); без vector DB
и embeddings. Метки автора (owner/created_by) — SET NULL при удалении пользователя.
"""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class RagFolder(Base):
    __tablename__ = "rag_folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    customer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="SET NULL")
    )
    object_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("project_objects.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # JSON-массив строк (логический путь в дереве базы знаний)
    path_json: Mapped[str | None] = mapped_column(Text)
    # ready | indexing | error | disabled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_rag_folders_customer", "customer_id"),
        Index("ix_rag_folders_object", "object_id"),
        Index("ix_rag_folders_status", "status"),
        Index("ix_rag_folders_owner", "owner_user_id"),
    )


class RagFolderDocument(Base):
    __tablename__ = "rag_folder_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rag_folders.id", ondelete="CASCADE")
    )
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE")
    )
    added_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("folder_id", "document_id", name="uq_rag_folder_document"),
        Index("ix_rag_folder_documents_folder", "folder_id"),
        Index("ix_rag_folder_documents_document", "document_id"),
    )
