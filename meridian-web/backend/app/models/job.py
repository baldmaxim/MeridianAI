"""Background job model (корп. стандарт §16: PostgreSQL-based jobs/outbox)."""

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Job(Base):
    """Очередь фоновых задач с атомарным захватом, ретраями и dead-state."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # pending | running | done | dead
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(64))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        # покрывает выборку claim: status + next_run_at
        Index("ix_jobs_claim", "status", "next_run_at"),
    )
