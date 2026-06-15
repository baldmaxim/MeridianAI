"""meeting context sources — previous meetings as context (Этап 8)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_context_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("added_by_user_id", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meeting_context_sources_meeting", "meeting_context_sources", ["meeting_id"], unique=False)
    op.create_index("ix_meeting_context_sources_type_source", "meeting_context_sources", ["source_type", "source_id"], unique=False)
    op.create_index("ix_meeting_context_sources_included", "meeting_context_sources", ["included"], unique=False)
    # partial-unique: один и тот же источник (с source_id) нельзя добавить дважды к встрече
    op.create_index(
        "uq_context_source", "meeting_context_sources",
        ["meeting_id", "source_type", "source_id"],
        unique=True, postgresql_where=sa.text("source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_context_source", table_name="meeting_context_sources")
    op.drop_index("ix_meeting_context_sources_included", table_name="meeting_context_sources")
    op.drop_index("ix_meeting_context_sources_type_source", table_name="meeting_context_sources")
    op.drop_index("ix_meeting_context_sources_meeting", table_name="meeting_context_sources")
    op.drop_table("meeting_context_sources")
