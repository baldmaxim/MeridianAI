"""AI settings profiles + meeting-level model controls (Этап 9)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_settings_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("profile_type", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column("stt_provider", sa.String(length=40), nullable=True),
        sa.Column("stt_model", sa.String(length=100), nullable=True),
        sa.Column("llm_provider", sa.String(length=40), nullable=True),
        sa.Column("live_suggestion_model", sa.String(length=100), nullable=True),
        sa.Column("strengthen_model", sa.String(length=100), nullable=True),
        sa.Column("finalization_model", sa.String(length=100), nullable=True),
        sa.Column("learning_model", sa.String(length=100), nullable=True),
        sa.Column("suggestion_mode", sa.String(length=20), nullable=False, server_default="balanced"),
        sa.Column("auto_suggestions_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("document_context_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("knowledge_context_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("previous_meetings_context_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("suggestion_structured_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("finalization_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("learning_extraction_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_auto_cards", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("max_manual_cards", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("auto_suggestion_min_interval_seconds", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("document_context_max_chunks", sa.Integer(), nullable=True),
        sa.Column("document_context_max_chars", sa.Integer(), nullable=True),
        sa.Column("previous_context_max_meetings", sa.Integer(), nullable=True),
        sa.Column("previous_context_max_chars", sa.Integer(), nullable=True),
        sa.Column("knowledge_context_max_items", sa.Integer(), nullable=True),
        sa.Column("settings_json", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_profiles_owner", "ai_settings_profiles", ["owner_user_id"], unique=False)
    op.create_index("ix_ai_profiles_owner_default", "ai_settings_profiles", ["owner_user_id", "is_default"], unique=False)
    op.create_index("ix_ai_profiles_type", "ai_settings_profiles", ["profile_type"], unique=False)
    # один default-профиль на владельца (partial unique, Postgres)
    op.create_index(
        "uq_ai_profile_default", "ai_settings_profiles", ["owner_user_id"],
        unique=True, postgresql_where=sa.text("is_default"),
    )

    op.add_column("meeting_sessions", sa.Column("ai_settings_profile_id", sa.Integer(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("ai_settings_snapshot_json", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_meeting_ai_profile", "meeting_sessions", "ai_settings_profiles",
        ["ai_settings_profile_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_meeting_sessions_ai_profile", "meeting_sessions", ["ai_settings_profile_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_meeting_sessions_ai_profile", table_name="meeting_sessions")
    op.drop_constraint("fk_meeting_ai_profile", "meeting_sessions", type_="foreignkey")
    op.drop_column("meeting_sessions", "ai_settings_snapshot_json")
    op.drop_column("meeting_sessions", "ai_settings_profile_id")

    op.drop_index("uq_ai_profile_default", table_name="ai_settings_profiles")
    op.drop_index("ix_ai_profiles_type", table_name="ai_settings_profiles")
    op.drop_index("ix_ai_profiles_owner_default", table_name="ai_settings_profiles")
    op.drop_index("ix_ai_profiles_owner", table_name="ai_settings_profiles")
    op.drop_table("ai_settings_profiles")
