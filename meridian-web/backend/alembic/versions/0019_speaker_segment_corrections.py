"""segment-level diarization corrections (Этап 8)

Overlay поверх raw STT: поправка стороны/спикера для отдельной реплики. Raw transcript
(transcript_segments) НЕ меняется.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_speaker_segment_corrections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("segment_key", sa.String(length=200), nullable=False),
        sa.Column("original_speaker_label", sa.String(length=120), nullable=True),
        sa.Column("corrected_speaker_label", sa.String(length=120), nullable=True),
        sa.Column("side", sa.String(length=20), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "segment_key", name="uq_meeting_speaker_segment_correction"),
    )
    op.create_index("ix_speaker_seg_corr_meeting", "meeting_speaker_segment_corrections", ["meeting_id"], unique=False)
    op.create_index("ix_speaker_seg_corr_segment", "meeting_speaker_segment_corrections", ["segment_key"], unique=False)
    op.create_index("ix_speaker_seg_corr_corrected_label", "meeting_speaker_segment_corrections", ["corrected_speaker_label"], unique=False)
    op.create_index("ix_speaker_seg_corr_side", "meeting_speaker_segment_corrections", ["side"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_speaker_seg_corr_side", table_name="meeting_speaker_segment_corrections")
    op.drop_index("ix_speaker_seg_corr_corrected_label", table_name="meeting_speaker_segment_corrections")
    op.drop_index("ix_speaker_seg_corr_segment", table_name="meeting_speaker_segment_corrections")
    op.drop_index("ix_speaker_seg_corr_meeting", table_name="meeting_speaker_segment_corrections")
    op.drop_table("meeting_speaker_segment_corrections")
