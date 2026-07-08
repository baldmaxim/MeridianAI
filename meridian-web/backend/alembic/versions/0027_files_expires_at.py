"""files.expires_at: срок авто-удаления для мини-облака (purpose="stash")

Мини-облако — личное временное хранилище файлов (обмен между устройствами).
Файлы stash авто-удаляются по expires_at (TTL, дефолт 7 дней). Колонка NULLABLE:
NULL для document/batch_audio/meeting_audio (у них своя ретенция по встрече).

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("files", "expires_at")
