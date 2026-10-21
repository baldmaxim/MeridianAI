"""meeting_sessions.app_notes: заметки пользователя из десктоп-приложения

Заметки приложения (строки `[мм:сс] текст`) раньше писались в meeting_notes и затирали
«Ключевые условия / цели» с сайта. Теперь у них своя колонка; meeting_notes остаётся контекстом
встречи (как на сайте).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_sessions", sa.Column("app_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("meeting_sessions", "app_notes")
