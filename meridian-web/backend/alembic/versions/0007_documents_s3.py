"""documents on S3 + chunks + meeting_documents link (Этап 4)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- documents ---
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("original_name", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_ext", sa.String(length=20), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("s3_bucket", sa.String(length=200), nullable=True),
        sa.Column("s3_key", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("sheet_count", sa.Integer(), nullable=True),
        sa.Column("extracted_text_s3_key", sa.String(length=500), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_owner", "documents", ["owner_user_id"], unique=False)
    op.create_index("ix_documents_customer", "documents", ["customer_id"], unique=False)
    op.create_index("ix_documents_object", "documents", ["object_id"], unique=False)
    op.create_index("ix_documents_status", "documents", ["status"], unique=False)

    # --- document_chunks ---
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.String(length=200), nullable=True),
        sa.Column("section_title", sa.String(length=300), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_chunks_doc", "document_chunks", ["document_id", "chunk_index"], unique=False)

    # --- meeting_documents: расширение под S3-flow (legacy-строки сохраняются) ---
    op.add_column("meeting_documents", sa.Column("document_id", sa.Integer(), nullable=True))
    op.add_column("meeting_documents", sa.Column("added_by_user_id", sa.Integer(), nullable=True))
    op.add_column("meeting_documents", sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("meeting_documents", sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()))
    # legacy NOT NULL → NULL (новые строки не несут inline-контент)
    op.alter_column("meeting_documents", "content", existing_type=sa.Text(), nullable=True)
    op.alter_column("meeting_documents", "filename", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("meeting_documents", "doc_type", existing_type=sa.String(length=50), nullable=True)
    op.create_foreign_key(
        "fk_meeting_documents_document", "meeting_documents", "documents",
        ["document_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_meeting_documents_added_by", "meeting_documents", "users",
        ["added_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_meeting_document", "meeting_documents", ["session_id", "document_id"])
    op.create_index("ix_meeting_documents_document", "meeting_documents", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_meeting_documents_document", table_name="meeting_documents")
    op.drop_constraint("uq_meeting_document", "meeting_documents", type_="unique")
    op.drop_constraint("fk_meeting_documents_added_by", "meeting_documents", type_="foreignkey")
    op.drop_constraint("fk_meeting_documents_document", "meeting_documents", type_="foreignkey")
    op.alter_column("meeting_documents", "doc_type", existing_type=sa.String(length=50), nullable=True)
    op.alter_column("meeting_documents", "filename", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("meeting_documents", "content", existing_type=sa.Text(), nullable=True)
    op.drop_column("meeting_documents", "included")
    op.drop_column("meeting_documents", "priority")
    op.drop_column("meeting_documents", "added_by_user_id")
    op.drop_column("meeting_documents", "document_id")

    op.drop_index("ix_document_chunks_doc", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_object", table_name="documents")
    op.drop_index("ix_documents_customer", table_name="documents")
    op.drop_index("ix_documents_owner", table_name="documents")
    op.drop_table("documents")
