"""directories (customers/objects/departments) + access model + meeting links

Этап 1 MVP: справочники заказчиков/объектов/отделов, модель доступа сотрудников
к объектам/встречам, новые поля в meeting_sessions.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- customers ---
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("inn", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_owner_name", "customers", ["owner_user_id", "name"], unique=False)

    # --- project_objects ---
    op.create_table(
        "project_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_objects_customer", "project_objects", ["customer_id"], unique=False)

    # --- departments ---
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

    # --- user_departments ---
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

    # --- object_access_grants ---
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

    # --- meeting_participants ---
    op.create_table(
        "meeting_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="participant"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "user_id", name="uq_meeting_participant"),
    )
    op.create_index("ix_meeting_participants_user", "meeting_participants", ["user_id"], unique=False)
    op.create_index("ix_meeting_participants_meeting", "meeting_participants", ["meeting_id"], unique=False)

    # --- meeting_sessions: новые поля ---
    op.add_column("meeting_sessions", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("object_id", sa.Integer(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("status", sa.String(length=30), nullable=True, server_default="active"))
    op.add_column("meeting_sessions", sa.Column("micro_summary", sa.Text(), nullable=True))
    op.add_column("meeting_sessions", sa.Column("tags_json", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_meeting_sessions_customer", "meeting_sessions", "customers",
        ["customer_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_meeting_sessions_object", "meeting_sessions", "project_objects",
        ["object_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_meeting_sessions_created_by", "meeting_sessions", "users",
        ["created_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_meeting_sessions_customer", "meeting_sessions", ["customer_id"], unique=False)
    op.create_index("ix_meeting_sessions_object", "meeting_sessions", ["object_id"], unique=False)

    # бэкфилл: created_by_user_id = user_id, status = 'active'
    op.execute("UPDATE meeting_sessions SET created_by_user_id = user_id WHERE created_by_user_id IS NULL")
    op.execute("UPDATE meeting_sessions SET status = 'active' WHERE status IS NULL")


def downgrade() -> None:
    op.drop_index("ix_meeting_sessions_object", table_name="meeting_sessions")
    op.drop_index("ix_meeting_sessions_customer", table_name="meeting_sessions")
    op.drop_constraint("fk_meeting_sessions_created_by", "meeting_sessions", type_="foreignkey")
    op.drop_constraint("fk_meeting_sessions_object", "meeting_sessions", type_="foreignkey")
    op.drop_constraint("fk_meeting_sessions_customer", "meeting_sessions", type_="foreignkey")
    op.drop_column("meeting_sessions", "tags_json")
    op.drop_column("meeting_sessions", "micro_summary")
    op.drop_column("meeting_sessions", "status")
    op.drop_column("meeting_sessions", "created_by_user_id")
    op.drop_column("meeting_sessions", "object_id")
    op.drop_column("meeting_sessions", "customer_id")

    op.drop_index("ix_meeting_participants_meeting", table_name="meeting_participants")
    op.drop_index("ix_meeting_participants_user", table_name="meeting_participants")
    op.drop_table("meeting_participants")

    op.drop_index("ix_object_access_grants_grantee_dept", table_name="object_access_grants")
    op.drop_index("ix_object_access_grants_grantee_user", table_name="object_access_grants")
    op.drop_index("ix_object_access_grants_object", table_name="object_access_grants")
    op.drop_table("object_access_grants")

    op.drop_index("ix_user_departments_department", table_name="user_departments")
    op.drop_index("ix_user_departments_user", table_name="user_departments")
    op.drop_table("user_departments")

    op.drop_index("ix_departments_owner_name", table_name="departments")
    op.drop_table("departments")

    op.drop_index("ix_project_objects_customer", table_name="project_objects")
    op.drop_table("project_objects")

    op.drop_index("ix_customers_owner_name", table_name="customers")
    op.drop_table("customers")
