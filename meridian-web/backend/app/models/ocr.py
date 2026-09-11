# -*- coding: utf-8 -*-
"""Распознавание сканов агентом на компьютере пользователя.

Модель chandra-ocr-2 живёт в LM Studio на домашнем компьютере за NAT: сервер до неё не
достучится, а открывать входящий порт на домашней машине не стоит. Поэтому направление
обращено, как в MailHub: сервер кладёт документ в очередь, агент сам забирает задачу по
HTTPS, распознаёт локально и возвращает текст.

OcrAgent — подключённый компьютер. В базе только sha256 токена: токен — 256 бит
случайности, перебором его не восстановить, а индекс по хэшу даёт поиск без перебора
всех агентов.

DocumentOcrTask — один документ на распознавание. Задача берётся в аренду, а не
помечается «занято»: компьютер могут выключить посреди работы, и снимать пометку было бы
некому — истёкшая аренда освобождает задачу сама.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class OcrAgent(Base):
    __tablename__ = "ocr_agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    model: Mapped[str | None] = mapped_column(String(200))
    agent_version: Mapped[str | None] = mapped_column(String(40))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class DocumentOcrTask(Base):
    __tablename__ = "document_ocr_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # pending | leased | done | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ocr_agents.id", ondelete="SET NULL")
    )
    pages_total: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_document_ocr_tasks_claim", "status", "lease_until"),
    )


class DocumentOcrPage(Base):
    """Распознанная страница. Агент сдаёт текст постранично, а не одним куском:
    договор на полторы сотни страниц в одном запросе упёрся бы в лимит тела запроса,
    а после перезагрузки компьютера распознавание не начинается с нуля — готовые
    страницы агент пропускает."""

    __tablename__ = "document_ocr_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("document_ocr_tasks.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("task_id", "page_number", name="uq_document_ocr_page"),
    )
