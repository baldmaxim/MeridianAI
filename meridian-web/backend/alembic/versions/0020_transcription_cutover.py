"""production cutover: speech timestamps + transcription epochs + multi-channel segments (Этап 9.8)

Аддитивно: nullable speech-time колонки в transcript_segments + две новые таблицы для
авторитетного multi-channel транскрипта. Существующие данные/поведение не затрагиваются.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- transcript_segments: speech-time метки (nullable, аддитивно) ---
    op.add_column("transcript_segments", sa.Column("speech_start_ms", sa.BigInteger(), nullable=True))
    op.add_column("transcript_segments", sa.Column("speech_end_ms", sa.BigInteger(), nullable=True))

    # --- эпохи транскрипции ---
    op.create_table(
        "meeting_transcription_epochs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("epoch_index", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("start_server_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_server_ms", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("automatic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("live_session_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "epoch_index", name="uq_transcription_epoch_meeting_index"),
    )
    op.create_index("ix_transcription_epoch_meeting", "meeting_transcription_epochs", ["meeting_id"], unique=False)

    # --- сохранённые multi-channel сегменты (нормализованный текст, без raw/PCM) ---
    op.create_table(
        "meeting_multi_channel_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("epoch_id", sa.Integer(), nullable=True),
        sa.Column("segment_key", sa.String(length=200), nullable=False),
        sa.Column("session_id", sa.String(length=40), nullable=False),
        sa.Column("channel_index", sa.Integer(), nullable=False),
        sa.Column("channel_label", sa.String(length=120), nullable=True),
        sa.Column("side", sa.String(length=20), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("start_server_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_server_ms", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["epoch_id"], ["meeting_transcription_epochs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "segment_key", name="uq_multi_channel_segment_key"),
    )
    op.create_index("ix_multi_channel_segment_meeting", "meeting_multi_channel_segments", ["meeting_id"], unique=False)
    op.create_index("ix_multi_channel_segment_epoch", "meeting_multi_channel_segments", ["epoch_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_multi_channel_segment_epoch", table_name="meeting_multi_channel_segments")
    op.drop_index("ix_multi_channel_segment_meeting", table_name="meeting_multi_channel_segments")
    op.drop_table("meeting_multi_channel_segments")
    op.drop_index("ix_transcription_epoch_meeting", table_name="meeting_transcription_epochs")
    op.drop_table("meeting_transcription_epochs")
    op.drop_column("transcript_segments", "speech_end_ms")
    op.drop_column("transcript_segments", "speech_start_ms")
