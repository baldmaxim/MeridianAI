"""Alembic migration environment."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

from app.config import get_settings
from app.database import Base, normalize_async_url
import app.models  # noqa: F401 — регистрирует ВСЕ таблицы в Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# §7: миграции под migration-пользователем (DDL). Пусто → фолбэк на database_url.
_settings = get_settings()
_RAW_DB_URL = _settings.migration_database_url or _settings.database_url
# asyncpg-драйвер + connect_args (ssl/pgbouncer) для Yandex Managed PG
DB_URL, CONNECT_ARGS = normalize_async_url(_RAW_DB_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(DB_URL, poolclass=pool.NullPool, connect_args=CONNECT_ARGS)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
