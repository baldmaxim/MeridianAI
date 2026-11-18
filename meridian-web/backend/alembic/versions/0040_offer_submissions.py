"""Подачи КП: documents.offer_submission + meeting_sessions.offer_submission.

documents.offer_submission — ключ подачи (имя папки) для import_source.kind="offer" ("" — вне папок),
NULL — документ общего контекста. meeting_sessions.offer_submission — обсуждаемая подача
(NULL — прежнее поведение: все документы объекта). Бэкфилл documents разбирает doc_meta в Python
(json, не jsonb — без БД-специфичных операторов).

Revision ID: 0040
Revises: 0039
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

_MAX_LEN = 300


def _submission_of(doc_meta) -> str | None:
    if isinstance(doc_meta, str):
        try:
            doc_meta = json.loads(doc_meta)
        except ValueError:
            return None
    if not isinstance(doc_meta, dict):
        return None
    source = doc_meta.get("import_source")
    if not isinstance(source, dict) or source.get("kind") != "offer":
        return None
    submission = source.get("submission")
    return submission.strip()[:_MAX_LEN] if isinstance(submission, str) else ""


def upgrade() -> None:
    op.add_column("documents", sa.Column("offer_submission", sa.String(_MAX_LEN), nullable=True))
    op.add_column("meeting_sessions", sa.Column("offer_submission", sa.String(_MAX_LEN), nullable=True))
    op.create_index(
        "ix_documents_object_offer_submission", "documents", ["object_id", "offer_submission"],
    )

    bind = op.get_bind()
    documents = sa.table(
        "documents", sa.column("id", sa.Integer), sa.column("doc_meta", sa.JSON),
        sa.column("offer_submission", sa.String),
    )
    for doc_id, doc_meta in bind.execute(
        sa.select(documents.c.id, documents.c.doc_meta).where(documents.c.doc_meta.is_not(None))
    ).all():
        submission = _submission_of(doc_meta)
        if submission is not None:
            bind.execute(
                documents.update().where(documents.c.id == doc_id).values(offer_submission=submission)
            )


def downgrade() -> None:
    op.drop_index("ix_documents_object_offer_submission", table_name="documents")
    op.drop_column("meeting_sessions", "offer_submission")
    op.drop_column("documents", "offer_submission")
