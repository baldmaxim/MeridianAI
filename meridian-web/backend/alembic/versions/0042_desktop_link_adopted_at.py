"""desktop_meeting_links.adopted_at: встреча принята приложением без локальной записи

«Продолжить в приложении» для встречи с сайта или другого ПК: у приложения нет прежнего
аудио, поэтому финализация такой встречи не запускает уточнение (оно стёрло бы
прежние реплики) и пустой список заметок не очищает заметки встречи.

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "desktop_meeting_links",
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("desktop_meeting_links", "adopted_at")
