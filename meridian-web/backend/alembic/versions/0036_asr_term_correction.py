"""батч: правка распознанного текста по словарю терминов

batch_jobs.transcription_corrections_json — правки словаря поверх transcription_json
({"v":1,"lexicon":...,"items":[{w0,w1,from,to,term}]}); исходное распознавание не меняется.
NULL — правку не пробовали (либо LLM не ответила), {"items": []} — править было нечего.
asr_terms — пользовательские термины словаря: owner_user_id NULL = общий для всех.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("batch_jobs", sa.Column("transcription_corrections_json", sa.Text(), nullable=True))
    op.create_table(
        "asr_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("term", sa.String(300), nullable=False),
        sa.Column("aliases_json", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="name"),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asr_terms_owner_user_id", "asr_terms", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_asr_terms_owner_user_id", table_name="asr_terms")
    op.drop_table("asr_terms")
    op.drop_column("batch_jobs", "transcription_corrections_json")
