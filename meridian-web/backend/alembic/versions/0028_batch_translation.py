"""batch_jobs.transcription_translation_json: русский перевод иноязычных реплик

Коллеги из Турции переключаются на свой язык по ходу встречи, распознавание сохраняет
речь как есть. Перевод храним отдельной колонкой, оригинал в transcription_json не
трогаем: word-level тайминги держат перемотку плеера и нарезку фрагментов.

Колонка NULLABLE: у старых задач и у одноязычных встреч перевода нет.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_jobs",
        sa.Column("transcription_translation_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("batch_jobs", "transcription_translation_json")
