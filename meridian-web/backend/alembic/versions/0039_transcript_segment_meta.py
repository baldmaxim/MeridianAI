"""Язык, перевод и метка говорящего (диаризация) у сохранённой реплики.

Revision ID: 0039
Revises: 0038
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transcript_segments", sa.Column("language", sa.String(16), nullable=True))
    op.add_column("transcript_segments", sa.Column("translation", sa.Text(), nullable=True))
    op.add_column("transcript_segments", sa.Column("diarized_speaker", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("transcript_segments", "diarized_speaker")
    op.drop_column("transcript_segments", "translation")
    op.drop_column("transcript_segments", "language")
