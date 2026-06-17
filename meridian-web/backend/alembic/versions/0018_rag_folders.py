"""rag folders — папки базы знаний и их подключение к контексту встречи (Этап 5)

Подключение папки к встрече хранится в существующей meeting_context_sources
(source_type='rag_folder', source_id=rag_folders.id) — её схема НЕ меняется.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_folders_customer", "rag_folders", ["customer_id"], unique=False)
    op.create_index("ix_rag_folders_object", "rag_folders", ["object_id"], unique=False)
    op.create_index("ix_rag_folders_status", "rag_folders", ["status"], unique=False)
    op.create_index("ix_rag_folders_owner", "rag_folders", ["owner_user_id"], unique=False)

    op.create_table(
        "rag_folder_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("added_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["folder_id"], ["rag_folders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("folder_id", "document_id", name="uq_rag_folder_document"),
    )
    op.create_index("ix_rag_folder_documents_folder", "rag_folder_documents", ["folder_id"], unique=False)
    op.create_index("ix_rag_folder_documents_document", "rag_folder_documents", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_rag_folder_documents_document", table_name="rag_folder_documents")
    op.drop_index("ix_rag_folder_documents_folder", table_name="rag_folder_documents")
    op.drop_table("rag_folder_documents")

    op.drop_index("ix_rag_folders_owner", table_name="rag_folders")
    op.drop_index("ix_rag_folders_status", table_name="rag_folders")
    op.drop_index("ix_rag_folders_object", table_name="rag_folders")
    op.drop_index("ix_rag_folders_customer", table_name="rag_folders")
    op.drop_table("rag_folders")
