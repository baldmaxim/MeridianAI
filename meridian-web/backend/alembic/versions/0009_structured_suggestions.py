"""structured suggestion cards: extend meeting_suggestions (Этап 6)

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting_suggestions", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column("meeting_suggestions", sa.Column("why", sa.Text(), nullable=True))
    op.add_column("meeting_suggestions", sa.Column("evidence_json", sa.Text(), nullable=True))
    op.add_column("meeting_suggestions", sa.Column("card_json", sa.Text(), nullable=True))
    op.add_column("meeting_suggestions", sa.Column("needs_user_check", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("meeting_suggestions", sa.Column("source_mode", sa.String(length=20), nullable=True))
    op.add_column("meeting_suggestions", sa.Column("priority", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("meeting_suggestions", "priority")
    op.drop_column("meeting_suggestions", "source_mode")
    op.drop_column("meeting_suggestions", "needs_user_check")
    op.drop_column("meeting_suggestions", "card_json")
    op.drop_column("meeting_suggestions", "evidence_json")
    op.drop_column("meeting_suggestions", "why")
    op.drop_column("meeting_suggestions", "title")
