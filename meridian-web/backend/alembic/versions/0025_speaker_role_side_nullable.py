"""meeting_speaker_roles.side → nullable: имя спикера без выбора стороны

Поимённое именование спикеров (display_name) должно сохраняться независимо от
стороны «Мы/Не мы». side становится NULLABLE: строка хранит имя, даже если сторона
не выбрана. Существующие строки не меняются (у них side уже задан).

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "meeting_speaker_roles", "side",
        existing_type=sa.String(length=20),
        nullable=True,
    )


def downgrade() -> None:
    # вернуть NOT NULL: строки без стороны пометить как opponent (консервативно)
    op.execute("UPDATE meeting_speaker_roles SET side = 'opponent' WHERE side IS NULL")
    op.alter_column(
        "meeting_speaker_roles", "side",
        existing_type=sa.String(length=20),
        nullable=False,
    )
