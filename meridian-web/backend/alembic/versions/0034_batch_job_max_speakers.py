"""batch_jobs.max_speakers: число говорящих, заданное при загрузке записи

NULL = «авто» (диаризация решает сама).

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("batch_jobs", sa.Column("max_speakers", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("batch_jobs", "max_speakers")
