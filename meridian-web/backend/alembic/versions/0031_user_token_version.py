"""users.token_version: отзыв access-токенов

Access-токен несёт claim `tv` = users.token_version. Смена пароля/роли, блокировка и
logout-all увеличивают версию — токены со старым `tv` перестают приниматься. Токены без
claim считаются версией 0, поэтому уже выданные токены живут до первого увеличения.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
