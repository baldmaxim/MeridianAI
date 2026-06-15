"""knowledge base + learning candidates (Этап 7)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _owner_cust_obj(prefix, table):
    op.create_index(f"ix_{prefix}_owner_status", table, ["owner_user_id", "status"], unique=False)
    op.create_index(f"ix_{prefix}_customer", table, ["customer_id"], unique=False)
    op.create_index(f"ix_{prefix}_object", table, ["object_id"], unique=False)


def upgrade() -> None:
    # --- learning_candidates ---
    op.create_table(
        "learning_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("meeting_id", sa.Integer(), nullable=True),
        sa.Column("candidate_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("source_refs_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meeting_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_candidates_owner_status", "learning_candidates", ["owner_user_id", "status"], unique=False)
    op.create_index("ix_learning_candidates_customer", "learning_candidates", ["customer_id"], unique=False)
    op.create_index("ix_learning_candidates_object", "learning_candidates", ["object_id"], unique=False)
    op.create_index("ix_learning_candidates_meeting", "learning_candidates", ["meeting_id"], unique=False)
    op.create_index("ix_learning_candidates_type_status", "learning_candidates", ["candidate_type", "status"], unique=False)

    # --- glossary_terms ---
    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("term", sa.String(length=300), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("aliases_json", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="approved"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_from_candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_from_meeting_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _owner_cust_obj("glossary", "glossary_terms")
    # partial-unique approved term within owner/customer/object/scope (Postgres)
    op.create_index(
        "uq_glossary_approved", "glossary_terms",
        ["owner_user_id", "customer_id", "object_id", "scope", "term"],
        unique=True, postgresql_where=sa.text("status = 'approved'"),
    )

    # --- trigger_phrases ---
    op.create_table(
        "trigger_phrases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("phrase", sa.String(length=500), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False, server_default="other"),
        sa.Column("recommended_reaction", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="approved"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_from_candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_from_meeting_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _owner_cust_obj("triggers", "trigger_phrases")
    op.create_index(
        "uq_triggers_approved", "trigger_phrases",
        ["owner_user_id", "customer_id", "object_id", "scope", "phrase"],
        unique=True, postgresql_where=sa.text("status = 'approved'"),
    )

    # --- negotiation_playbooks ---
    op.create_table(
        "negotiation_playbooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("situation", sa.Text(), nullable=False),
        sa.Column("recommended_phrase", sa.Text(), nullable=False),
        sa.Column("technique", sa.String(length=30), nullable=False, server_default="other"),
        sa.Column("ask_in_return_json", sa.Text(), nullable=True),
        sa.Column("risks_json", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="approved"),
        sa.Column("success_score", sa.Float(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_from_candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_from_meeting_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _owner_cust_obj("playbooks", "negotiation_playbooks")

    # --- counterparty_traits ---
    op.create_table(
        "counterparty_traits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("trait", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("recommended_strategy", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="customer"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="approved"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_from_candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_from_meeting_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _owner_cust_obj("traits", "counterparty_traits")

    # --- forbidden_phrases ---
    op.create_table(
        "forbidden_phrases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("phrase_or_risk", sa.Text(), nullable=False),
        sa.Column("better_alternative", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="approved"),
        sa.Column("created_from_candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_from_meeting_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_id"], ["project_objects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _owner_cust_obj("forbidden", "forbidden_phrases")

    # --- meeting_sessions: learning status ---
    op.add_column("meeting_sessions", sa.Column("learning_status", sa.String(length=20), nullable=False, server_default="not_started"))
    op.add_column("meeting_sessions", sa.Column("learning_error", sa.Text(), nullable=True))


def _drop_owner_cust_obj(prefix, table):
    op.drop_index(f"ix_{prefix}_object", table_name=table)
    op.drop_index(f"ix_{prefix}_customer", table_name=table)
    op.drop_index(f"ix_{prefix}_owner_status", table_name=table)


def downgrade() -> None:
    op.drop_column("meeting_sessions", "learning_error")
    op.drop_column("meeting_sessions", "learning_status")

    _drop_owner_cust_obj("forbidden", "forbidden_phrases")
    op.drop_table("forbidden_phrases")
    _drop_owner_cust_obj("traits", "counterparty_traits")
    op.drop_table("counterparty_traits")
    _drop_owner_cust_obj("playbooks", "negotiation_playbooks")
    op.drop_table("negotiation_playbooks")
    op.drop_index("uq_triggers_approved", table_name="trigger_phrases")
    _drop_owner_cust_obj("triggers", "trigger_phrases")
    op.drop_table("trigger_phrases")
    op.drop_index("uq_glossary_approved", table_name="glossary_terms")
    _drop_owner_cust_obj("glossary", "glossary_terms")
    op.drop_table("glossary_terms")

    op.drop_index("ix_learning_candidates_type_status", table_name="learning_candidates")
    op.drop_index("ix_learning_candidates_meeting", table_name="learning_candidates")
    op.drop_index("ix_learning_candidates_object", table_name="learning_candidates")
    op.drop_index("ix_learning_candidates_customer", table_name="learning_candidates")
    op.drop_index("ix_learning_candidates_owner_status", table_name="learning_candidates")
    op.drop_table("learning_candidates")
