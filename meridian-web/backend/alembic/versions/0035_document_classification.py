"""documents: автоклассификация (тип, теги, метаданные)

doc_type — тип из закрытого списка, doc_tags — теги из закрытого списка (JSON-массив),
doc_meta — извлечённые реквизиты (ИНН/БИН, номер, дата, сумма; без полного текста),
classify_source — чем определён тип (rules | llm), classified_at — когда.
Все колонки nullable: старые документы остаются неклассифицированными до повторной обработки.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("doc_type", sa.String(30), nullable=True))
    op.add_column("documents", sa.Column("doc_tags", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("doc_meta", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("classify_source", sa.String(10), nullable=True))
    op.add_column("documents", sa.Column("classified_at", sa.DateTime(), nullable=True))
    op.create_index("ix_documents_doc_type", "documents", ["doc_type"])


def downgrade() -> None:
    op.drop_index("ix_documents_doc_type", table_name="documents")
    op.drop_column("documents", "classified_at")
    op.drop_column("documents", "classify_source")
    op.drop_column("documents", "doc_meta")
    op.drop_column("documents", "doc_tags")
    op.drop_column("documents", "doc_type")
