"""Persisted speaker roles for conversation tree

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_speaker_roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("speaker_label", sa.String(length=255), nullable=False),
        sa.Column("side", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "speaker_label", name="uq_speaker_role_meeting_label"),
    )
    op.create_index("ix_speaker_roles_meeting", "meeting_speaker_roles", ["meeting_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_speaker_roles_meeting", table_name="meeting_speaker_roles")
    op.drop_table("meeting_speaker_roles")
