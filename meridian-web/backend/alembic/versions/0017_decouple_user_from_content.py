"""decouple user from meetings/documents/objects (CASCADE -> SET NULL)

Общая хронология: встречи, документы, заказчики и объекты больше не принадлежат
пользователю. Поля автора (user_id / owner_user_id / created_by_user_id) становятся
информативной меткой и при удалении пользователя обнуляются (SET NULL), а сама запись
сохраняется. Раньше удаление пользователя каскадом сносило все его встречи, транскрипты,
протоколы, документы, заказчиков и объекты — главный риск потери данных.

Имена FK — Postgres-конвенция для inline-констрейнтов: <table>_<column>_fkey.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


# (table, column, fk_name)
_LINKS = [
    ("meeting_sessions", "user_id", "meeting_sessions_user_id_fkey"),
    ("saved_transcriptions", "user_id", "saved_transcriptions_user_id_fkey"),
    ("customers", "owner_user_id", "customers_owner_user_id_fkey"),
    ("project_objects", "owner_user_id", "project_objects_owner_user_id_fkey"),
    ("documents", "owner_user_id", "documents_owner_user_id_fkey"),
    ("documents", "created_by_user_id", "documents_created_by_user_id_fkey"),
]


def upgrade() -> None:
    for table, column, fk in _LINKS:
        op.alter_column(table, column, existing_type=sa.Integer(), nullable=True)
        op.drop_constraint(fk, table, type_="foreignkey")
        op.create_foreign_key(
            fk, table, "users", [column], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    # ВНИМАНИЕ: при наличии строк с NULL в этих колонках downgrade упадёт на NOT NULL —
    # это ожидаемо (данные «осиротевших» записей нельзя восстановить).
    for table, column, fk in _LINKS:
        op.drop_constraint(fk, table, type_="foreignkey")
        op.create_foreign_key(
            fk, table, "users", [column], ["id"], ondelete="CASCADE"
        )
        op.alter_column(table, column, existing_type=sa.Integer(), nullable=False)
