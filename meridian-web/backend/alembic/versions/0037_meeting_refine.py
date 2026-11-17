"""десктоп-встречи: уточнение транскрипта через ElevenLabs

meeting_sessions.refine_status — pending|running|done|failed|skipped (NULL — уточнение не применялось);
refine_error — короткое сообщение о сбое; transcript_draft_json — черновой транскрипт с ПК до замены
(для отката); refined_at — когда уточнённый транскрипт записан.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_sessions", sa.Column("refine_status", sa.String(20), nullable=True))
    op.add_column("meeting_sessions", sa.Column("refine_error", sa.Text(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("transcript_draft_json", sa.Text(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("refined_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("meeting_sessions", "refined_at")
    op.drop_column("meeting_sessions", "transcript_draft_json")
    op.drop_column("meeting_sessions", "refine_error")
    op.drop_column("meeting_sessions", "refine_status")
