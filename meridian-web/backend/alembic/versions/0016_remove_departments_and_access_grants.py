"""remove departments/access grants, add users.department

Упрощение модели: справочники убраны. Сущность «Отдел» и все её связи
(object_access_grants, user_departments, departments) удаляются. Отдел теперь —
строковый атрибут пользователя (users.department), указывается при регистрации.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users.department (свободный текст, отдел сотрудника) ---
    op.add_column("users", sa.Column("department", sa.String(length=120), nullable=True))

    # --- удалить выдачу доступа к объектам ---
    op.drop_index("ix_object_access_grants_grantee_dept", table_name="object_access_grants")
    op.drop_index("ix_object_access_grants_grantee_user", table_name="object_access_grants")
    op.drop_index("ix_object_access_grants_object", table_name="object_access_grants")
    op.drop_table("object_access_grants")

    # --- удалить отдел-сущность и членство ---
    op.drop_index("ix_user_departments_department", table_name="user_departments")
    op.drop_index("ix_user_departments_user", table_name="user_departments")
    op.drop_table("user_departments")

    op.drop_index("ix_departments_owner_name", table_name="departments")
    op.drop_table("departments")


def downgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_departments_owner_name", "departments", ["owner_user_id", "name"], unique=False)

    op.create_table(
        "user_departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "department_id", name="uq_user_department"),
    )
    op.create_index("ix_user_departments_user", "user_departments", ["user_id"], unique=False)
    op.create_index("ix_user_departments_department", "user_departments", ["department_id"], unique=False)

    op.create_table(
        "object_access_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("grantee_type", sa.String(length=20), nullable=False),
        sa.Column("grantee_user_id", sa.Integer(), nullable=True),
        sa.Column("grantee_department_id", sa.Integer(), nullable=True),
        sa.Column("access_level", sa.String(length=20), nullable=False, server_default="view"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grantee_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grantee_department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_object_access_grants_object", "object_access_grants", ["object_id"], unique=False)
    op.create_index("ix_object_access_grants_grantee_user", "object_access_grants", ["grantee_user_id"], unique=False)
    op.create_index("ix_object_access_grants_grantee_dept", "object_access_grants", ["grantee_department_id"], unique=False)

    op.drop_column("users", "department")
