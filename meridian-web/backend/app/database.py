"""Database engine and session management."""

import uuid
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

settings = get_settings()

# Корп. стандарт §7: только PostgreSQL. SQLite больше не поддерживается.
if "sqlite" in settings.database_url:
    raise RuntimeError(
        "SQLite не поддерживается (корп. стандарт §7). "
        "Используйте PostgreSQL: docker compose -f docker-compose.dev.yml up -d, "
        "затем DATABASE_URL=postgresql+asyncpg://..."
    )


def normalize_async_url(raw: str) -> tuple[str, dict]:
    """URL → asyncpg-драйвер + connect_args для Yandex Managed PostgreSQL.

    - схему ``postgresql://`` приводим к ``postgresql+asyncpg://`` (psycopg2 не используется);
    - для нелокального хоста включаем ``ssl=require`` (Yandex требует TLS);
    - Yandex фронтит pgbouncer (transaction pooling), несовместимый с prepared statements
      asyncpg → ``statement_cache_size=0`` + уникальные имена statement'ов.
    Query-параметры (sslmode и т.п.) выносятся в connect_args, т.к. asyncpg их не понимает в URL.
    """
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql://", "postgres://"):
        if raw.startswith(prefix):
            raw = "postgresql+asyncpg://" + raw[len(prefix):]
            break
    host = urlsplit(raw).hostname or ""
    is_local = host in ("localhost", "127.0.0.1", "")
    clean = raw.split("?", 1)[0]  # asyncpg не понимает sslmode в URL → задаём через connect_args
    connect_args: dict = {}
    if "+asyncpg" in clean:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid.uuid4()}__"
        if not is_local:
            connect_args["ssl"] = "require"
    return clean, connect_args


_db_url, _connect_args = normalize_async_url(settings.database_url)

# Явный пул соединений (§5/§7); pool_pre_ping снимает «битые» коннекты после простоя/рестарта БД.
engine = create_async_engine(
    _db_url,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency: get async database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
