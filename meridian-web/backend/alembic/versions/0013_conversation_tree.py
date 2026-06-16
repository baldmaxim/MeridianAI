"""Conversation tree (Дерево общения встречи) + AI-toggle

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_conversation_topics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("normalized_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("our_summary", sa.Text(), nullable=True),
        sa.Column("opponent_summary", sa.Text(), nullable=True),
        sa.Column("our_last_text", sa.Text(), nullable=True),
        sa.Column("opponent_last_text", sa.Text(), nullable=True),
        sa.Column("our_refs_json", sa.Text(), nullable=True),
        sa.Column("opponent_refs_json", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "normalized_key", name="uq_conv_topic_meeting_key"),
    )
    op.create_index("ix_conv_topics_meeting", "meeting_conversation_topics", ["meeting_id"], unique=False)
    op.create_index("ix_conv_topics_key", "meeting_conversation_topics", ["normalized_key"], unique=False)
    op.create_index("ix_conv_topics_status", "meeting_conversation_topics", ["status"], unique=False)
    op.create_index("ix_conv_topics_last_updated", "meeting_conversation_topics", ["last_updated_at"], unique=False)

    op.add_column(
        "ai_settings_profiles",
        sa.Column("conversation_tree_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("ai_settings_profiles", "conversation_tree_enabled")

    op.drop_index("ix_conv_topics_last_updated", table_name="meeting_conversation_topics")
    op.drop_index("ix_conv_topics_status", table_name="meeting_conversation_topics")
    op.drop_index("ix_conv_topics_key", table_name="meeting_conversation_topics")
    op.drop_index("ix_conv_topics_meeting", table_name="meeting_conversation_topics")
    op.drop_table("meeting_conversation_topics")
