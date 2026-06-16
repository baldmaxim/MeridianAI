"""Role-based page access (доступ к страницам по роли)

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-16
"""

import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


# Сид-дефолты дублируют app/core/pages.py (миграция не импортирует app-код).
# admin — все страницы; user — Проекты + Оффлайн распознавание (как было до миграции).
_ADMIN_PAGES = [
    "objects", "batch", "dir-objects", "dir-departments",
    "knowledge", "ai-settings", "settings",
]
_USER_PAGES = ["objects", "batch"]


def upgrade() -> None:
    op.create_table(
        "role_page_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role_name", sa.String(length=20), nullable=False),
        sa.Column("allowed_pages", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_name", name="uq_role_page_access_role"),
    )
    op.create_index("ix_role_page_access_role", "role_page_access", ["role_name"], unique=True)

    now = datetime.utcnow()
    table = sa.table(
        "role_page_access",
        sa.column("role_name", sa.String),
        sa.column("allowed_pages", sa.Text),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        table,
        [
            {
                "role_name": "admin",
                "allowed_pages": json.dumps(_ADMIN_PAGES, ensure_ascii=False),
                "created_at": now,
                "updated_at": now,
            },
            {
                "role_name": "user",
                "allowed_pages": json.dumps(_USER_PAGES, ensure_ascii=False),
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_role_page_access_role", table_name="role_page_access")
    op.drop_table("role_page_access")
