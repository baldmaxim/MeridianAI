"""meeting_sessions.diarization_max_speakers: число спикеров диаризации на встречу

Каждая встреча — своё число спикеров (разное число людей). Колонка NULLABLE:
NULL = унаследовать дефолт владельца (user_settings.diarization_max_speakers).
Существующие встречи получают NULL → дефолт владельца.

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meeting_sessions",
        sa.Column("diarization_max_speakers", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meeting_sessions", "diarization_max_speakers")
