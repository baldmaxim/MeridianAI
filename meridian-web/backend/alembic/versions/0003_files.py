"""files table (§15: S3 presigned uploads, soft delete)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column("original_name", sa.String(length=500), nullable=False),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("mime", sa.String(length=100), nullable=True),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_files_user_id", "files", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_files_user_id", table_name="files")
    op.drop_table("files")
