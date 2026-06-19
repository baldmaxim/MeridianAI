"""meeting recorded_seconds: суммарное время активной записи (диктофон)

Аддитивно: NOT NULL колонка с server_default 0 в meeting_sessions. Накапливается
инкрементом на каждый стоп записи (старт→стоп диктофона), а не как ended_at − started_at
(время открытой сессии). Существующие строки получают 0.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meeting_sessions",
        sa.Column("recorded_seconds", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("meeting_sessions", "recorded_seconds")
