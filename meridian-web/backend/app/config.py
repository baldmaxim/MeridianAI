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

    # Audit (§22): ключ HMAC для email в audit_log. Пусто → фолбэк на JWT_SECRET.
    audit_hmac_key: str = Field(default="", alias="AUDIT_HMAC_KEY")

    # Keycloak OIDC (§9/§12). AUTH_MODE: local | keycloak | both (default local — деплой inert).
    auth_mode: str = Field(default="local", alias="AUTH_MODE")
    oidc_issuer: str = Field(default="", alias="OIDC_ISSUER")  # https://auth.su10.ru/realms/su10
    oidc_client_id: str = Field(default="", alias="OIDC_CLIENT_ID")
    oidc_client_secret: str = Field(default="", alias="OIDC_CLIENT_SECRET")
    oidc_redirect_uri: str = Field(default="", alias="OIDC_REDIRECT_URI")
    # URL фронта, куда callback вернёт токен (по умолчанию первый CORS-origin)
    frontend_url: str = Field(default="", alias="FRONTEND_URL")

    @property
    def oidc_enabled(self) -> bool:
        return self.auth_mode in ("keycloak", "both") and bool(
            self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret
        )

    # S3-совместимое хранилище (§15). Включается при заданных endpoint+bucket+ключах.
    s3_endpoint: str = Field(default="", alias="S3_ENDPOINT")
    s3_region: str = Field(default="ru-central-1", alias="S3_REGION")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_access_key: str = Field(default="", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="", alias="S3_SECRET_KEY")
    s3_presign_ttl: int = Field(default=900, alias="S3_PRESIGN_TTL")

    # Документы встречи (Этап 4): загрузка на S3, извлечение текста, чанкинг, контекст
    document_max_upload_mb: int = Field(default=50, alias="DOCUMENT_MAX_UPLOAD_MB")
    document_allowed_extensions: str = Field(
        default=".pdf,.docx,.xlsx,.txt,.md,.csv", alias="DOCUMENT_ALLOWED_EXTENSIONS"
    )
    document_chunk_target_chars: int = Field(default=7000, alias="DOCUMENT_CHUNK_TARGET_CHARS")
    document_chunk_overlap_chars: int = Field(default=1000, alias="DOCUMENT_CHUNK_OVERLAP_CHARS")
    document_context_max_chunks: int = Field(default=6, alias="DOCUMENT_CONTEXT_MAX_CHUNKS")
    document_context_max_chars: int = Field(default=14000, alias="DOCUMENT_CONTEXT_MAX_CHARS")
    # RAG-папки в контекст подсказок (Этап 5). v1 — лексический retrieval поверх DocumentChunk.
    rag_context_enabled: bool = Field(default=True, alias="RAG_CONTEXT_ENABLED")
    rag_context_max_chunks: int = Field(default=8, alias="RAG_CONTEXT_MAX_CHUNKS")
    rag_context_max_chars: int = Field(default=12000, alias="RAG_CONTEXT_MAX_CHARS")

    # Context Pack (Этап 6): верхний уровень бюджета сборки prompt. Per-mode общий лимит
    # и per-block лимиты. Старые provider-лимиты (DOCUMENT_CONTEXT_*) остаются внутренними.
    context_pack_auto_max_chars: int = Field(default=22000, alias="CONTEXT_PACK_AUTO_MAX_CHARS")
    context_pack_manual_max_chars: int = Field(default=48000, alias="CONTEXT_PACK_MANUAL_MAX_CHARS")
    context_pack_strengthen_max_chars: int = Field(default=72000, alias="CONTEXT_PACK_STRENGTHEN_MAX_CHARS")
    context_pack_meeting_context_max_chars: int = Field(default=4000, alias="CONTEXT_PACK_MEETING_CONTEXT_MAX_CHARS")
    context_pack_recent_dialog_max_chars: int = Field(default=16000, alias="CONTEXT_PACK_RECENT_DIALOG_MAX_CHARS")
    context_pack_full_transcript_max_chars: int = Field(default=36000, alias="CONTEXT_PACK_FULL_TRANSCRIPT_MAX_CHARS")
    context_pack_document_max_chars: int = Field(default=16000, alias="CONTEXT_PACK_DOCUMENT_MAX_CHARS")
    context_pack_rag_max_chars: int = Field(default=14000, alias="CONTEXT_PACK_RAG_MAX_CHARS")
    context_pack_knowledge_max_chars: int = Field(default=8000, alias="CONTEXT_PACK_KNOWLEDGE_MAX_CHARS")
    context_pack_previous_max_chars: int = Field(default=16000, alias="CONTEXT_PACK_PREVIOUS_MAX_CHARS")
    context_pack_trace_enabled: bool = Field(default=True, alias="CONTEXT_PACK_TRACE_ENABLED")

    # Observer-диаризация (Этап 9): второй телефон шлёт только числовые метрики уровня звука
    # (RMS/peak/VAD), НЕ raw audio. Backend сравнивает уровни вокруг committed-реплики и
    # выдаёт подсказку «вероятно Мы/Не мы». Auto-apply по умолчанию ВЫКЛЮЧЕН.
    observer_diarization_enabled: bool = Field(default=True, alias="OBSERVER_DIARIZATION_ENABLED")
    observer_diarization_auto_apply: bool = Field(default=False, alias="OBSERVER_DIARIZATION_AUTO_APPLY")
    observer_diarization_window_ms: int = Field(default=1800, alias="OBSERVER_DIARIZATION_WINDOW_MS")
    observer_diarization_min_rms: float = Field(default=0.025, alias="OBSERVER_DIARIZATION_MIN_RMS")
    observer_diarization_ratio: float = Field(default=1.35, alias="OBSERVER_DIARIZATION_RATIO")
    observer_diarization_min_confidence: float = Field(default=0.65, alias="OBSERVER_DIARIZATION_MIN_CONFIDENCE")
    observer_diarization_max_metrics_per_device: int = Field(default=600, alias="OBSERVER_DIARIZATION_MAX_METRICS_PER_DEVICE")
    document_max_extract_chars: int = Field(default=3_000_000, alias="DOCUMENT_MAX_EXTRACT_CHARS")
    s3_document_prefix: str = Field(default="documents", alias="S3_DOCUMENT_PREFIX")
    s3_extracted_text_prefix: str = Field(default="documents_extracted", alias="S3_EXTRACTED_TEXT_PREFIX")

    @property
    def s3_enabled(self) -> bool:
        return bool(self.s3_endpoint and self.s3_bucket and self.s3_access_key and self.s3_secret_key)

    @property
    def document_allowed_extensions_set(self) -> set[str]:
        return {e.strip().lower() for e in self.document_allowed_extensions.split(",") if e.strip()}

    # Финализация встречи (Этап 5): фоновое формирование протокола через LLM
    meeting_finalization_enabled: bool = Field(default=True, alias="MEETING_FINALIZATION_ENABLED")
    meeting_finalization_model: str = Field(default="", alias="MEETING_FINALIZATION_MODEL")  # ""→дефолт LLM
    meeting_finalization_max_transcript_chars: int = Field(default=120000, alias="MEETING_FINALIZATION_MAX_TRANSCRIPT_CHARS")
    meeting_finalization_max_document_chars: int = Field(default=20000, alias="MEETING_FINALIZATION_MAX_DOCUMENT_CHARS")
    meeting_finalization_timeout_seconds: int = Field(default=180, alias="MEETING_FINALIZATION_TIMEOUT_SECONDS")
    meeting_finalization_retry_attempts: int = Field(default=2, alias="MEETING_FINALIZATION_RETRY_ATTEMPTS")

    @property
    def finalization_model(self) -> str:
        return self.meeting_finalization_model or "google/gemini-3-flash-preview"

    # Структурированные live-подсказки (Этап 6)
    suggestion_structured_enabled: bool = Field(default=True, alias="SUGGESTION_STRUCTURED_ENABLED")
    suggestion_repair_enabled: bool = Field(default=True, alias="SUGGESTION_REPAIR_ENABLED")
    suggestion_max_cards_auto: int = Field(default=2, alias="SUGGESTION_MAX_CARDS_AUTO")
    suggestion_max_cards_manual: int = Field(default=5, alias="SUGGESTION_MAX_CARDS_MANUAL")
    suggestion_evidence_required_for_high_confidence: bool = Field(
        default=True, alias="SUGGESTION_EVIDENCE_REQUIRED_FOR_HIGH_CONFIDENCE"
    )

    # Controlled auto-learning (Этап 7)
    learning_extraction_enabled: bool = Field(default=True, alias="LEARNING_EXTRACTION_ENABLED")
    learning_extraction_min_confidence: float = Field(default=0.55, alias="LEARNING_EXTRACTION_MIN_CONFIDENCE")
    learning_extraction_max_candidates: int = Field(default=15, alias="LEARNING_EXTRACTION_MAX_CANDIDATES")
    learning_extraction_model: str = Field(default="", alias="LEARNING_EXTRACTION_MODEL")
    learning_extraction_timeout_seconds: int = Field(default=120, alias="LEARNING_EXTRACTION_TIMEOUT_SECONDS")
    learning_extraction_repair_enabled: bool = Field(default=True, alias="LEARNING_EXTRACTION_REPAIR_ENABLED")
    learning_context_max_transcript_chars: int = Field(default=40000, alias="LEARNING_CONTEXT_MAX_TRANSCRIPT_CHARS")

    @property
    def learning_model(self) -> str:
        return self.learning_extraction_model or "google/gemini-3-flash-preview"

    # Предыдущие встречи как контекст (Этап 8) — только компактные итоги, не транскрипты
    previous_meetings_context_enabled: bool = Field(default=True, alias="PREVIOUS_MEETINGS_CONTEXT_ENABLED")
    previous_meetings_context_max_meetings: int = Field(default=5, alias="PREVIOUS_MEETINGS_CONTEXT_MAX_MEETINGS")
    previous_meetings_context_max_chars: int = Field(default=20000, alias="PREVIOUS_MEETINGS_CONTEXT_MAX_CHARS")
    previous_meetings_context_per_meeting_max_chars: int = Field(default=4000, alias="PREVIOUS_MEETINGS_CONTEXT_PER_MEETING_MAX_CHARS")
    previous_meetings_candidates_limit: int = Field(default=20, alias="PREVIOUS_MEETINGS_CANDIDATES_LIMIT")

    # Session idle TTL in seconds (cleanup abandoned sessions)
    session_idle_ttl: int = Field(default=3600, alias="SESSION_IDLE_TTL")

    # --- Этап 10: production hardening ---
    app_version: str = Field(default="0.11.0", alias="APP_VERSION")

    # Jobs/worker (§16)
    job_max_attempts: int = Field(default=3, alias="JOB_MAX_ATTEMPTS")
    job_retry_base_seconds: int = Field(default=30, alias="JOB_RETRY_BASE_SECONDS")
    job_error_max_chars: int = Field(default=2000, alias="JOB_ERROR_MAX_CHARS")
    job_stale_running_minutes: int = Field(default=30, alias="JOB_STALE_RUNNING_MINUTES")
    worker_poll_interval_seconds: float = Field(default=2.0, alias="WORKER_POLL_INTERVAL_SECONDS")

    # WebSocket / MeetingRoom
    ws_max_binary_frame_bytes: int = Field(default=2 * 1024 * 1024, alias="WS_MAX_BINARY_FRAME_BYTES")
    meeting_room_idle_ttl_minutes: int = Field(default=120, alias="MEETING_ROOM_IDLE_TTL_MINUTES")
    ws_heartbeat_interval_seconds: int = Field(default=30, alias="WS_HEARTBEAT_INTERVAL_SECONDS")
    ws_client_timeout_seconds: int = Field(default=120, alias="WS_CLIENT_TIMEOUT_SECONDS")

    # Загрузка batch-аудио (S3)
    audio_max_upload_mb: int = Field(default=500, alias="AUDIO_MAX_UPLOAD_MB")

    @property
    def s3_configured(self) -> bool:
        return self.s3_enabled

    def safe_config_summary(self) -> dict:
        """Безопасные флаги конфигурации (БЕЗ секретов) для health/диагностики."""
        return {
            "version": self.app_version,
            "environment": self.environment,
            "dev_mode": self.dev_mode,
            "auth_mode": self.auth_mode,
            "oidc_enabled": self.oidc_enabled,
            "s3_configured": self.s3_enabled,
            "sentry_enabled": bool(self.sentry_dsn),
            "encryption_configured": bool(self.encryption_key),
            "finalization_enabled": self.meeting_finalization_enabled,
            "learning_extraction_enabled": self.learning_extraction_enabled,
            "previous_meetings_context_enabled": self.previous_meetings_context_enabled,
            "rag_context_enabled": self.rag_context_enabled,
            "context_pack_trace_enabled": self.context_pack_trace_enabled,
            "observer_diarization_enabled": self.observer_diarization_enabled,
            "observer_diarization_auto_apply": self.observer_diarization_auto_apply,
            "context_pack_auto_max_chars": self.context_pack_auto_max_chars,
            "context_pack_manual_max_chars": self.context_pack_manual_max_chars,
            "context_pack_strengthen_max_chars": self.context_pack_strengthen_max_chars,
            "document_max_upload_mb": self.document_max_upload_mb,
            "audio_max_upload_mb": self.audio_max_upload_mb,
            "job_max_attempts": self.job_max_attempts,
            "job_stale_running_minutes": self.job_stale_running_minutes,
            "ws_max_binary_frame_bytes": self.ws_max_binary_frame_bytes,
            "allowed_document_extensions": sorted(self.document_allowed_extensions_set),
        }

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
