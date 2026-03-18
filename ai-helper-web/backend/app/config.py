"""Application configuration."""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://ai_helper:ai_helper@localhost:5432/ai_helper",
        alias="DATABASE_URL",
    )

    # JWT
    jwt_secret: str = Field(default="change-me-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # File storage
    upload_dir: str = Field(default="uploads", alias="UPLOAD_DIR")
    transcription_dir: str = Field(default="transcriptions", alias="TRANSCRIPTION_DIR")

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Encryption key for API keys in DB
    encryption_key: str = Field(default="", alias="ENCRYPTION_KEY")

    # Dev mode: auto-migration, pick-folder, ad-hoc ALTER TABLE
    dev_mode: bool = Field(default=True, alias="DEV_MODE")

    # Session idle TTL in seconds (cleanup abandoned sessions)
    session_idle_ttl: int = Field(default=3600, alias="SESSION_IDLE_TTL")

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
