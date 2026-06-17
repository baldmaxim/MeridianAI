"""Тестовая инфраструктура (Этап 1 MVP).

Каждый тест получает изолированную сессию с откатом транзакции в конце —
ничего не коммитится (безопасно даже против общей БД).

Выбор БД (приоритет):
  1. TEST_DATABASE_URL — отдельная тестовая БД;
  2. иначе DATABASE_URL из настроек (Yandex/dev Postgres).

URL вида ``postgresql://``/``postgresql+psycopg2://`` автоматически приводится к
asyncpg-драйверу; для нелокального хоста включается ssl=require (без правки .env).
Для локального прогона можно указать ``TEST_DATABASE_URL=sqlite+aiosqlite:///:memory:``.
"""

import os

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from app.config import get_settings
from app.database import Base, normalize_async_url
import app.models  # noqa: F401 — регистрирует все таблицы в Base.metadata


def _make_engine():
    raw = os.environ.get("TEST_DATABASE_URL") or get_settings().database_url
    if raw.startswith("sqlite"):
        engine = create_async_engine(
            raw, poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        # SQLite по умолчанию не применяет ON DELETE SET NULL/CASCADE — включаем,
        # чтобы тесты FK-поведения (отвязка при удалении пользователя) были валидны.
        @event.listens_for(engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _rec):  # pragma: no cover
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    # тот же нормализатор, что и у приложения: asyncpg + ssl + pgbouncer-safe (Yandex)
    url, connect_args = normalize_async_url(raw)
    return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = _make_engine()
    # таблицы (idempotent; для Postgres после alembic upgrade head — no-op)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    connection = await engine.connect()
    trans = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        if trans.is_active:
            await trans.rollback()
        await connection.close()
        await engine.dispose()
