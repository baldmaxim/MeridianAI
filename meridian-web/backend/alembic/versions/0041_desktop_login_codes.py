"""desktop_login_codes: вход десктоп-приложения через браузер

Приложение открывает сайт, пользователь подтверждает вход, сайт получает одноразовый код
(в базе только sha256 кода и challenge), приложение меняет код + verifier на токен устройства.
Код живёт две минуты и принимает одну попытку.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_login_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("code_challenge", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
    )
    op.create_index("ix_desktop_login_codes_user_id", "desktop_login_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_desktop_login_codes_user_id", table_name="desktop_login_codes")
    op.drop_table("desktop_login_codes")
