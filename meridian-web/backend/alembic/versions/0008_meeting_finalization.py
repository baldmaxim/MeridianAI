"""meeting finalization: protocol fields + decisions/action_items/risks/open_questions (Этап 5)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- meeting_sessions: поля финализации ---
    op.add_column("meeting_sessions", sa.Column("finalization_status", sa.String(length=20), nullable=False, server_default="not_started"))
    op.add_column("meeting_sessions", sa.Column("finalized_at", sa.DateTime(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("protocol_markdown", sa.Text(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("protocol_json", sa.Text(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("summary_json", sa.Text(), nullable=True))

    # --- meeting_decisions ---
    op.create_table(
        "meeting_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unclear"),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meeting_decisions_meeting", "meeting_decisions", ["meeting_id"], unique=False)
    op.create_index("ix_meeting_decisions_status", "meeting_decisions", ["status"], unique=False)

    # --- meeting_action_items ---
    op.create_table(
        "meeting_action_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("owner_text", sa.String(length=255), nullable=True),
        sa.Column("due_text", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meeting_action_items_meeting", "meeting_action_items", ["meeting_id"], unique=False)
    op.create_index("ix_meeting_action_items_status", "meeting_action_items", ["status"], unique=False)

    # --- meeting_risks ---
    op.create_table(
        "meeting_risks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meeting_risks_meeting", "meeting_risks", ["meeting_id"], unique=False)
    op.create_index("ix_meeting_risks_severity", "meeting_risks", ["severity"], unique=False)

    # --- meeting_open_questions ---
    op.create_table(
        "meeting_open_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meeting_open_questions_meeting", "meeting_open_questions", ["meeting_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_meeting_open_questions_meeting", table_name="meeting_open_questions")
    op.drop_table("meeting_open_questions")
    op.drop_index("ix_meeting_risks_severity", table_name="meeting_risks")
    op.drop_index("ix_meeting_risks_meeting", table_name="meeting_risks")
    op.drop_table("meeting_risks")
    op.drop_index("ix_meeting_action_items_status", table_name="meeting_action_items")
    op.drop_index("ix_meeting_action_items_meeting", table_name="meeting_action_items")
    op.drop_table("meeting_action_items")
    op.drop_index("ix_meeting_decisions_status", table_name="meeting_decisions")
    op.drop_index("ix_meeting_decisions_meeting", table_name="meeting_decisions")
    op.drop_table("meeting_decisions")

    op.drop_column("meeting_sessions", "summary_json")
    op.drop_column("meeting_sessions", "protocol_json")
    op.drop_column("meeting_sessions", "protocol_markdown")
    op.drop_column("meeting_sessions", "finalized_at")
    op.drop_column("meeting_sessions", "finalization_status")
