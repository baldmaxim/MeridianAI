"""user_settings.batch_stt_provider: провайдер офлайн-распознавания

Отдельно от stt_provider (он общий для живых встреч и не должен получать 'gigaam').
NULL = как в живой встрече.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings", sa.Column("batch_stt_provider", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user_settings", "batch_stt_provider")
