"""meeting audio links: files.meeting_id, batch_jobs.meeting_id, batch_jobs.kind

Аддитивно (§8): nullable FK meeting_id в files и batch_jobs + kind в batch_jobs.
- files.meeting_id — привязка архива живого аудио встречи (Задача 3, purpose='meeting_audio').
- batch_jobs.meeting_id + kind — дозапись офлайн-«дыры» в транскрипт встречи (Задача 5, kind='gap_fill').
NULL → не привязано к встрече (обычный батч/файл). ON DELETE SET NULL — запись файла переживает удаление встречи.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("meeting_id", sa.Integer(), nullable=True))
    op.create_index("ix_files_meeting_id", "files", ["meeting_id"])
    op.create_foreign_key(
        "fk_files_meeting_id", "files", "meeting_sessions",
        ["meeting_id"], ["id"], ondelete="SET NULL",
    )

    op.add_column("batch_jobs", sa.Column("meeting_id", sa.Integer(), nullable=True))
    op.create_index("ix_batch_jobs_meeting_id", "batch_jobs", ["meeting_id"])
    op.create_foreign_key(
        "fk_batch_jobs_meeting_id", "batch_jobs", "meeting_sessions",
        ["meeting_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column("batch_jobs", sa.Column("kind", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("batch_jobs", "kind")
    op.drop_constraint("fk_batch_jobs_meeting_id", "batch_jobs", type_="foreignkey")
    op.drop_index("ix_batch_jobs_meeting_id", table_name="batch_jobs")
    op.drop_column("batch_jobs", "meeting_id")

    op.drop_constraint("fk_files_meeting_id", "files", type_="foreignkey")
    op.drop_index("ix_files_meeting_id", table_name="files")
    op.drop_column("files", "meeting_id")
