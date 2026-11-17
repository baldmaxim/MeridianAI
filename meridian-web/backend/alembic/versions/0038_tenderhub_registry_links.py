"""Link TenderHub registry rows to Meridian objects.

Revision ID: 0038
Revises: 0037
"""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenderhub_registry_links",
        sa.Column("registry_id", sa.String(36), primary_key=True),
        sa.Column(
            "object_id", sa.Integer(),
            sa.ForeignKey("project_objects.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("registry_data", sa.JSON(), nullable=False),
    )
    op.create_index("ix_tenderhub_registry_links_object_id", "tenderhub_registry_links", ["object_id"])


def downgrade() -> None:
    op.drop_table("tenderhub_registry_links")
