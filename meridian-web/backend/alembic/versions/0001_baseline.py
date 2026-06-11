"""baseline schema

Базовая схема Meridian — соответствует моделям app/models/* на момент перехода
с create_all() на Alembic (корп. стандарт §8). Серверные DEFAULT не задаются:
значения по умолчанию проставляет ORM (как и при create_all).

Revision ID: 0001
Revises:
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(length=50), nullable=False),
        sa.Column("encrypted_key", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stt_provider", sa.String(length=20), nullable=False),
        sa.Column("llm_model", sa.String(length=100), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("user_role", sa.String(length=50), nullable=False),
        sa.Column("use_streaming", sa.Boolean(), nullable=False),
        sa.Column("diarization", sa.Boolean(), nullable=False),
        sa.Column("silence_filter", sa.Boolean(), nullable=False),
        sa.Column("custom_suggestion_types", sa.Text(), nullable=True),
        sa.Column("custom_trigger_keywords", sa.Text(), nullable=True),
        sa.Column("local_storage_path", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "meeting_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("meeting_topic", sa.Text(), nullable=True),
        sa.Column("meeting_notes", sa.Text(), nullable=True),
        sa.Column("negotiation_type", sa.String(length=50), nullable=True),
        sa.Column("meeting_role", sa.String(length=255), nullable=True),
        sa.Column("opponent_weaknesses", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("audio_path", sa.String(length=500), nullable=True),
        sa.Column("is_finalized", sa.Boolean(), nullable=False),
        sa.Column("finalization_error", sa.Text(), nullable=True),
        sa.Column("live_segment_count", sa.Integer(), nullable=True),
        sa.Column("final_segment_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "negotiation_roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("interests", sa.Text(), nullable=False),
        sa.Column("opponents", sa.Text(), nullable=False),
        sa.Column("custom_instructions", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("original_size", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("compressed_path", sa.String(length=500), nullable=True),
        sa.Column("compressed_size", sa.Integer(), nullable=True),
        sa.Column("transcription_text", sa.Text(), nullable=True),
        sa.Column("transcription_json", sa.Text(), nullable=True),
        sa.Column("protocol_markdown", sa.Text(), nullable=True),
        sa.Column("protocol_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_batch_jobs_user_id", "batch_jobs", ["user_id"], unique=False)

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.String(length=12), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("wall_clock", sa.DateTime(), nullable=False),
        sa.Column("speaker_id", sa.String(length=50), nullable=False),
        sa.Column("speaker_label", sa.String(length=100), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("avg_logprob", sa.Float(), nullable=True),
        sa.Column("min_logprob", sa.Float(), nullable=True),
        sa.Column("words_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("segment_id"),
    )
    op.create_index(
        "ix_transcript_segments_session_id", "transcript_segments", ["session_id"], unique=False
    )

    op.create_table(
        "meeting_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_auto", sa.Boolean(), nullable=False),
        sa.Column("suggestion_type", sa.String(length=20), nullable=True),
        sa.Column("trigger", sa.String(length=255), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("context_info", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meeting_suggestions_session_id", "meeting_suggestions", ["session_id"], unique=False
    )

    op.create_table(
        "meeting_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meeting_documents_session_id", "meeting_documents", ["session_id"], unique=False
    )

    op.create_table(
        "saved_transcriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("saved_transcriptions")
    op.drop_index("ix_meeting_documents_session_id", table_name="meeting_documents")
    op.drop_table("meeting_documents")
    op.drop_index("ix_meeting_suggestions_session_id", table_name="meeting_suggestions")
    op.drop_table("meeting_suggestions")
    op.drop_index("ix_transcript_segments_session_id", table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_index("ix_batch_jobs_user_id", table_name="batch_jobs")
    op.drop_table("batch_jobs")
    op.drop_table("negotiation_roles")
    op.drop_table("meeting_sessions")
    op.drop_table("user_settings")
    op.drop_table("api_keys")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
