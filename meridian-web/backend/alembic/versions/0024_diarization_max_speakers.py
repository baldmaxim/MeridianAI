"""user_settings.diarization_max_speakers: настраиваемый лимит спикеров диаризации

Аддитивно: NOT NULL колонка с server_default 3 в user_settings. Существующие строки
получают 3 (текущее поведение Speechmatics). UI ограничивает диапазон 2..6.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "diarization_max_speakers",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "diarization_max_speakers")
