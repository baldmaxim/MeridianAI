"""Database engine and session management."""

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

# Явный пул соединений (§5/§7); pool_pre_ping снимает «битые» коннекты после простоя/рестарта БД.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
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
