"""desktop_devices + desktop_meeting_links: десктоп-приложение записи встреч

Приложение на ПК пишет встречу локально, распознаёт её на месте и при появлении сети
отправляет на сервер. Устройство входит по паролю и получает токен (в базе только его
sha256, как у OCR-агентов). Связь (user_id, client_uuid) → встреча делает приём встречи
идемпотентным: повтор запроса после обрыва сети вернёт ту же встречу, а не создаст вторую.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("platform", sa.String(20)),
        sa.Column("app_version", sa.String(40)),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("last_seen_at", sa.DateTime()),
        sa.Column("revoked_at", sa.DateTime()),
    )
    op.create_index("ix_desktop_devices_user_id", "desktop_devices", ["user_id"])
    op.create_table(
        "desktop_meeting_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.Integer(),
                  sa.ForeignKey("desktop_devices.id", ondelete="SET NULL")),
        sa.Column("client_uuid", sa.String(36), nullable=False),
        sa.Column("meeting_id", sa.Integer(),
                  sa.ForeignKey("meeting_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_mode", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("user_id", "client_uuid", name="uq_desktop_meeting_link_client"),
    )
    op.create_index("ix_desktop_meeting_links_meeting_id", "desktop_meeting_links", ["meeting_id"])


def downgrade() -> None:
    op.drop_index("ix_desktop_meeting_links_meeting_id", table_name="desktop_meeting_links")
    op.drop_table("desktop_meeting_links")
    op.drop_index("ix_desktop_devices_user_id", table_name="desktop_devices")
    op.drop_table("desktop_devices")
