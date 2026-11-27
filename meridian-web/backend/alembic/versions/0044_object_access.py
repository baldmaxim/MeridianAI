"""Ручная выдача доступа к проектам: гранты по объекту/заказчику и заявки на доступ

users.all_objects_access — флаг «все проекты» (бэкфилл: true для действующих пользователей,
чтобы текущая работа не сломалась; новые пользователи получают false). Админ видит всё всегда.

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-27
"""

from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("all_objects_access", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE users SET all_objects_access = true WHERE is_active = true")

    op.create_table(
        "user_object_access",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("project_objects.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("granted_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_table(
        "user_customer_access",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("granted_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_table(
        "object_access_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("project_objects.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index(
        "uq_object_access_requests_pending", "object_access_requests", ["user_id", "object_id"],
        unique=True, postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_object_access_requests_status", "object_access_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_object_access_requests_status", table_name="object_access_requests")
    op.drop_index("uq_object_access_requests_pending", table_name="object_access_requests")
    op.drop_table("object_access_requests")
    op.drop_table("user_customer_access")
    op.drop_table("user_object_access")
    op.drop_column("users", "all_objects_access")
