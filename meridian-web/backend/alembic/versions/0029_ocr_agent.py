"""ocr_agents + document_ocr_tasks: распознавание сканов агентом на компьютере пользователя

Модель chandra-ocr-2 работает в LM Studio на домашнем компьютере за NAT, сервер до неё не
достучится. Как в MailHub, направление обращено: документ ставится в очередь, агент сам
забирает задачу по HTTPS и возвращает распознанный текст. Задача арендуется, а не
блокируется — выключенный посреди работы компьютер не оставит её висеть.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("last_seen_at", sa.DateTime()),
        sa.Column("model", sa.String(200)),
        sa.Column("agent_version", sa.String(40)),
        sa.Column("revoked_at", sa.DateTime()),
    )
    op.create_table(
        "document_ocr_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("ocr_agents.id", ondelete="SET NULL")),
        sa.Column("pages_total", sa.Integer()),
        sa.Column("model", sa.String(200)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_document_ocr_tasks_claim", "document_ocr_tasks", ["status", "lease_until"])
    # Текст сдаётся постранично: без лимита тела запроса и с продолжением после перезагрузки ПК.
    op.create_table(
        "document_ocr_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(),
                  sa.ForeignKey("document_ocr_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("task_id", "page_number", name="uq_document_ocr_page"),
    )


def downgrade() -> None:
    op.drop_table("document_ocr_pages")
    op.drop_index("ix_document_ocr_tasks_claim", table_name="document_ocr_tasks")
    op.drop_table("document_ocr_tasks")
    op.drop_table("ocr_agents")
