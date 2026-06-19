"""project_objects.payhub_project_id: маппинг объекта на проект PayHub

Аддитивно: nullable BIGINT в project_objects. Используется для сужения RAG-поиска писем
(внешнее pgvector-хранилище PayHub) по project_id для конкретной встречи. NULL → весь корпус.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_objects",
        sa.Column("payhub_project_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_objects", "payhub_project_id")
