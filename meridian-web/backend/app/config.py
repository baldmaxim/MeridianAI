"""Application configuration."""

from typing import Annotated

from pydantic_settings import BaseSettings, NoDecode
from pydantic import Field, field_validator
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://meridian:meridian@localhost:5432/meridian",
        alias="DATABASE_URL",
    )
    # Отдельный URL для миграций (§7: migration-пользователь с DDL-правами).
    # Пусто → миграции идут под database_url (dev-фолбэк).
    migration_database_url: str = Field(default="", alias="MIGRATION_DATABASE_URL")

    # Пул соединений (§5/§7: задаётся явно)
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")

    # JWT
    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # File storage
    upload_dir: str = Field(default="uploads", alias="UPLOAD_DIR")
    transcription_dir: str = Field(default="transcriptions", alias="TRANSCRIPTION_DIR")

    # CORS — точный allowlist (§23). Override через CORS_ORIGINS (JSON или CSV).
    # NoDecode: не давать env-источнику делать json.loads до валидатора (иначе CSV падает).
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:3000",
            "https://meridian.fvds.ru",
        ],
        alias="CORS_ORIGINS",
    )

    # Encryption key for API keys in DB
    encryption_key: str = Field(default="", alias="ENCRYPTION_KEY")

    # Dev mode: auto-migration, pick-folder, ad-hoc ALTER TABLE
    dev_mode: bool = Field(default=True, alias="DEV_MODE")

    # Observability (§20) — Sentry включается заданием DSN; иначе выключен
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # S3-совместимое хранилище (§15). Включается при заданных endpoint+bucket+ключах.
    s3_endpoint: str = Field(default="", alias="S3_ENDPOINT")
    s3_region: str = Field(default="ru-central-1", alias="S3_REGION")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_access_key: str = Field(default="", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="", alias="S3_SECRET_KEY")
    s3_presign_ttl: int = Field(default=900, alias="S3_PRESIGN_TTL")

    @property
    def s3_enabled(self) -> bool:
        return bool(self.s3_endpoint and self.s3_bucket and self.s3_access_key and self.s3_secret_key)

    # Session idle TTL in seconds (cleanup abandoned sessions)
    session_idle_ttl: int = Field(default=3600, alias="SESSION_IDLE_TTL")

    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v):
        """Принять как JSON-список, так и CSV-строку из env."""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json
                return json.loads(s)
            return [o.strip() for o in s.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
