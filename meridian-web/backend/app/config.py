"""Application configuration."""

from typing import Annotated

from pydantic_settings import BaseSettings, NoDecode
from pydantic import Field, field_validator, model_validator
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
            "https://app.example.com",
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

    # LM Studio — локальная машина с OpenAI-совместимым API (токен хранится
    # зашифрованно в api_keys под сервисом "lm_studio"). Несекретные дефолты:
    lmstudio_base_url: str = Field(
        default="http://localhost:1234/v1", alias="LMSTUDIO_BASE_URL"
    )
    lmstudio_ocr_model: str = Field(default="chandra-ocr-2", alias="LMSTUDIO_OCR_MODEL")
    lmstudio_lift_model: str = Field(default="lift", alias="LMSTUDIO_LIFT_MODEL")
    lmstudio_llm_model: str = Field(default="qwen36-27b-mtp", alias="LMSTUDIO_LLM_MODEL")

    # Keycloak OIDC (§9/§12). AUTH_MODE: local | keycloak | both (default local — деплой inert).
    auth_mode: str = Field(default="local", alias="AUTH_MODE")
    oidc_issuer: str = Field(default="", alias="OIDC_ISSUER")  # https://auth.example.com/realms/your-realm
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

    @property
    def letters_rag_effective_enabled(self) -> bool:
        """Письма PayHub реально доступны: флаг включён И заданы url+api_key+query_model."""
        return bool(
            self.letters_rag_enabled
            and self.pgvector_db_url
            and self.yandex_api_key
            and self.yandex_embedding_query_model
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

    # Письма PayHub (внешнее read-only pgvector, схема rag, vector(768) cosine). Гибридный
    # поиск + RAG-augmentation подсказок. Отдельный источник от внутренних RAG-папок (kind=letters).
    # Эффективно включается только при заданных url+api_key+query_model (см. letters_rag_effective_enabled).
    letters_rag_enabled: bool = Field(default=True, alias="PGVECTOR_LETTERS_ENABLED")
    pgvector_db_url: str = Field(default="", alias="PGVECTOR_DB_URL")
    pgvector_ca_cert_path: str = Field(default="", alias="PGVECTOR_CA_CERT_PATH")
    yandex_api_key: str = Field(default="", alias="YANDEX_API_KEY")
    yandex_folder_id: str = Field(default="", alias="YANDEX_FOLDER_ID")
    yandex_embedding_query_model: str = Field(default="", alias="YANDEX_EMBEDDING_QUERY_MODEL")
    yandex_embedding_dim: int = Field(default=768, alias="YANDEX_EMBEDDING_DIM")
    yandex_embedding_endpoint: str = Field(
        default="https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding",
        alias="YANDEX_EMBEDDING_ENDPOINT",
    )
    yandex_embedding_timeout_seconds: int = Field(default=30, alias="YANDEX_EMBEDDING_TIMEOUT_SECONDS")
    letters_embedding_cache_size: int = Field(default=256, alias="LETTERS_EMBEDDING_CACHE_SIZE")
    letters_search_timeout_seconds: int = Field(default=10, alias="LETTERS_SEARCH_TIMEOUT_SECONDS")
    letters_context_k: int = Field(default=6, alias="LETTERS_CONTEXT_K")
    letters_context_throttle_seconds: int = Field(default=20, alias="LETTERS_CONTEXT_THROTTLE_SECONDS")
    context_pack_letters_max_chars: int = Field(default=12000, alias="CONTEXT_PACK_LETTERS_MAX_CHARS")

    # Таблица проектов PayHub (read-only) — источник реальных названий для экрана связки
    # «проект PayHub → наш объект». Это ИДЕНТИФИКАТОРЫ (не значения): их нельзя биндить как
    # $-параметры asyncpg, поэтому имена строго валидируются регуляркой и квотируются (см.
    # rag_letters/store.py). Пусто → список проектов вернётся пустым (мягкая деградация).
    payhub_projects_table: str = Field(default="", alias="PAYHUB_PROJECTS_TABLE")
    payhub_projects_id_col: str = Field(default="id", alias="PAYHUB_PROJECTS_ID_COL")
    payhub_projects_name_col: str = Field(default="name", alias="PAYHUB_PROJECTS_NAME_COL")

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

    # Secondary audio shadow (Этап 9.2): дополнительное устройство стримит аудио-чанки
    # для будущего multi-channel. Чанки буферизуются in-memory и НЕ идут в STT, НЕ меняют
    # active_audio_source. Это отдельный режим от observer (тот шлёт только RMS/peak/VAD).
    secondary_audio_shadow_enabled: bool = Field(default=True, alias="SECONDARY_AUDIO_SHADOW_ENABLED")
    secondary_audio_shadow_max_devices: int = Field(default=4, alias="SECONDARY_AUDIO_SHADOW_MAX_DEVICES")
    secondary_audio_shadow_max_buffer_seconds: int = Field(default=120, alias="SECONDARY_AUDIO_SHADOW_MAX_BUFFER_SECONDS")
    secondary_audio_shadow_target_sample_rate: int = Field(default=16000, alias="SECONDARY_AUDIO_SHADOW_TARGET_SAMPLE_RATE")
    secondary_audio_shadow_max_chunk_ms: int = Field(default=250, alias="SECONDARY_AUDIO_SHADOW_MAX_CHUNK_MS")
    secondary_audio_shadow_max_chunk_bytes: int = Field(default=32000, alias="SECONDARY_AUDIO_SHADOW_MAX_CHUNK_BYTES")
    secondary_audio_shadow_accept_pcm16: bool = Field(default=True, alias="SECONDARY_AUDIO_SHADOW_ACCEPT_PCM16")
    secondary_audio_shadow_accept_float32: bool = Field(default=False, alias="SECONDARY_AUDIO_SHADOW_ACCEPT_FLOAT32")

    # Multi-source ingest (Этап 9.3): единый server-side слой для всех аудиоисточников
    # встречи. Primary-поток продолжает идти в STT БЕЗ изменений, а параллельно (tap)
    # и secondary-чанки приводятся к общей server timeline и режутся на canonical frames
    # с общим frame_index. Пока БЕЗ mux/WAV/STT для secondary. Окно PCM ограничено.
    multi_source_ingest_enabled: bool = Field(default=True, alias="MULTI_SOURCE_INGEST_ENABLED")
    multi_source_ingest_frame_ms: int = Field(default=20, alias="MULTI_SOURCE_INGEST_FRAME_MS")
    multi_source_ingest_window_seconds: int = Field(default=8, alias="MULTI_SOURCE_INGEST_WINDOW_SECONDS")
    multi_source_ingest_max_tracks: int = Field(default=6, alias="MULTI_SOURCE_INGEST_MAX_TRACKS")

    # Multi-channel WAV export (Этап 9.4): диагностический многоканальный WAV из текущего
    # ingest-окна. Один track = один WAV-канал; пропуски — тишиной только в файле; ручной
    # sample-level offset на канал. БЕЗ диска/БД/S3/STT/mux. Только download через authAPI.
    multi_channel_export_enabled: bool = Field(default=True, alias="MULTI_CHANNEL_EXPORT_ENABLED")
    multi_channel_export_max_channels: int = Field(default=4, alias="MULTI_CHANNEL_EXPORT_MAX_CHANNELS")
    multi_channel_export_default_seconds: int = Field(default=30, alias="MULTI_CHANNEL_EXPORT_DEFAULT_SECONDS")
    multi_channel_export_max_seconds: int = Field(default=120, alias="MULTI_CHANNEL_EXPORT_MAX_SECONDS")
    multi_channel_export_max_bytes: int = Field(default=33554432, alias="MULTI_CHANNEL_EXPORT_MAX_BYTES")
    multi_channel_export_max_offset_ms: int = Field(default=2000, alias="MULTI_CHANNEL_EXPORT_MAX_OFFSET_MS")

    # Batch multi-channel STT preview (Этап 9.5): отправка собранного in-memory WAV во
    # внешний batch STT (Deepgram prerecorded multichannel) ради ДИАГНОСТИЧЕСКОГО кандидата.
    # Live transcript не заменяется, ничего не сохраняется. По умолчанию ВЫКЛЮЧЕНО.
    multi_channel_batch_stt_enabled: bool = Field(default=False, alias="MULTI_CHANNEL_BATCH_STT_ENABLED")
    multi_channel_batch_stt_provider: str = Field(default="deepgram", alias="MULTI_CHANNEL_BATCH_STT_PROVIDER")
    multi_channel_batch_stt_model: str = Field(default="nova-3", alias="MULTI_CHANNEL_BATCH_STT_MODEL")
    multi_channel_batch_stt_language: str = Field(default="ru", alias="MULTI_CHANNEL_BATCH_STT_LANGUAGE")
    multi_channel_batch_stt_timeout_seconds: int = Field(default=180, alias="MULTI_CHANNEL_BATCH_STT_TIMEOUT_SECONDS")
    multi_channel_batch_stt_min_channels: int = Field(default=2, alias="MULTI_CHANNEL_BATCH_STT_MIN_CHANNELS")
    multi_channel_batch_stt_max_channels: int = Field(default=4, alias="MULTI_CHANNEL_BATCH_STT_MAX_CHANNELS")
    multi_channel_batch_stt_min_duration_seconds: int = Field(default=3, alias="MULTI_CHANNEL_BATCH_STT_MIN_DURATION_SECONDS")
    multi_channel_batch_stt_max_seconds: int = Field(default=120, alias="MULTI_CHANNEL_BATCH_STT_MAX_SECONDS")
    multi_channel_batch_stt_max_wav_bytes: int = Field(default=33554432, alias="MULTI_CHANNEL_BATCH_STT_MAX_WAV_BYTES")
    multi_channel_batch_stt_max_response_bytes: int = Field(default=10485760, alias="MULTI_CHANNEL_BATCH_STT_MAX_RESPONSE_BYTES")
    multi_channel_batch_stt_result_ttl_seconds: int = Field(default=900, alias="MULTI_CHANNEL_BATCH_STT_RESULT_TTL_SECONDS")
    multi_channel_batch_stt_max_global_jobs: int = Field(default=2, alias="MULTI_CHANNEL_BATCH_STT_MAX_GLOBAL_JOBS")
    deepgram_batch_url: str = Field(default="https://api.deepgram.com/v1/listen", alias="DEEPGRAM_BATCH_URL")

    # Realtime multi-channel live STT shadow (Этап 9.6): выбранные primary/secondary каналы
    # mux-ятся в один realtime PCM16-multichannel stream и шлются в ОТДЕЛЬНОЕ realtime STT
    # соединение. Это ДИАГНОСТИЧЕСКИЙ candidate: основной STT/подсказки/transcript не меняются.
    # Ничего не сохраняется. По умолчанию ВЫКЛЮЧЕНО.
    multi_channel_live_enabled: bool = Field(default=False, alias="MULTI_CHANNEL_LIVE_ENABLED")
    # Авто-оркестрация: когда в комнате есть primary-источник И активный shadow-трек,
    # backend сам поднимает live multi-channel (без ручного старта из UI). Гейтится также
    # `multi_channel_live_enabled` (master) и наличием ключа провайдера. Можно отключить,
    # оставив только ручной старт. По умолчанию ВКЛ (но мастер-флаг по умолчанию ВЫКЛ).
    multi_channel_live_autostart: bool = Field(default=True, alias="MULTI_CHANNEL_LIVE_AUTOSTART")
    multi_channel_live_provider: str = Field(default="deepgram", alias="MULTI_CHANNEL_LIVE_PROVIDER")
    multi_channel_live_model: str = Field(default="nova-3", alias="MULTI_CHANNEL_LIVE_MODEL")
    multi_channel_live_language: str = Field(default="ru", alias="MULTI_CHANNEL_LIVE_LANGUAGE")
    multi_channel_live_min_channels: int = Field(default=2, alias="MULTI_CHANNEL_LIVE_MIN_CHANNELS")
    multi_channel_live_max_channels: int = Field(default=4, alias="MULTI_CHANNEL_LIVE_MAX_CHANNELS")
    # Латентность (задача 2): снижены дефолты prebuffer/playout, чтобы reconciliation-кандидат
    # появлялся быстрее. Primary live-транскрипт это не затрагивает (shadow вне его пути).
    multi_channel_live_playout_delay_ms: int = Field(default=300, alias="MULTI_CHANNEL_LIVE_PLAYOUT_DELAY_MS")
    multi_channel_live_min_prebuffer_ms: int = Field(default=600, alias="MULTI_CHANNEL_LIVE_MIN_PREBUFFER_MS")
    multi_channel_live_send_chunk_ms: int = Field(default=100, alias="MULTI_CHANNEL_LIVE_SEND_CHUNK_MS")
    multi_channel_live_send_queue_chunks: int = Field(default=30, alias="MULTI_CHANNEL_LIVE_SEND_QUEUE_CHUNKS")
    multi_channel_live_track_stale_grace_ms: int = Field(default=3000, alias="MULTI_CHANNEL_LIVE_TRACK_STALE_GRACE_MS")
    multi_channel_live_secondary_silence_stop_ms: int = Field(default=15000, alias="MULTI_CHANNEL_LIVE_SECONDARY_SILENCE_STOP_MS")
    multi_channel_live_start_timeout_seconds: int = Field(default=15, alias="MULTI_CHANNEL_LIVE_START_TIMEOUT_SECONDS")
    multi_channel_live_close_timeout_seconds: int = Field(default=8, alias="MULTI_CHANNEL_LIVE_CLOSE_TIMEOUT_SECONDS")
    multi_channel_live_keepalive_seconds: int = Field(default=4, alias="MULTI_CHANNEL_LIVE_KEEPALIVE_SECONDS")
    multi_channel_live_interim_broadcast_ms: int = Field(default=250, alias="MULTI_CHANNEL_LIVE_INTERIM_BROADCAST_MS")
    multi_channel_live_state_broadcast_ms: int = Field(default=1000, alias="MULTI_CHANNEL_LIVE_STATE_BROADCAST_MS")
    multi_channel_live_max_final_segments: int = Field(default=2000, alias="MULTI_CHANNEL_LIVE_MAX_FINAL_SEGMENTS")
    multi_channel_live_max_session_seconds: int = Field(default=7200, alias="MULTI_CHANNEL_LIVE_MAX_SESSION_SECONDS")
    multi_channel_live_max_global_sessions: int = Field(default=2, alias="MULTI_CHANNEL_LIVE_MAX_GLOBAL_SESSIONS")
    multi_channel_live_silence_warn_ratio: float = Field(default=0.25, alias="MULTI_CHANNEL_LIVE_SILENCE_WARN_RATIO")
    deepgram_streaming_url: str = Field(default="wss://api.deepgram.com/v1/listen", alias="DEEPGRAM_STREAMING_URL")

    # Channel-aware reconciliation (Этап 9.7): сопоставление final multi-channel candidate с
    # committed-репликами основного transcript (по времени + тексту) для РУЧНОГО применения
    # стороны через существующий слой segment corrections. In-memory, ничего не сохраняется,
    # raw transcript не меняется, ничего автоматически не применяется.
    multi_channel_reconciliation_enabled: bool = Field(default=True, alias="MULTI_CHANNEL_RECONCILIATION_ENABLED")
    multi_channel_reconciliation_max_primary_segments: int = Field(default=1000, alias="MULTI_CHANNEL_RECONCILIATION_MAX_PRIMARY_SEGMENTS")
    multi_channel_reconciliation_max_candidate_segments: int = Field(default=2000, alias="MULTI_CHANNEL_RECONCILIATION_MAX_CANDIDATE_SEGMENTS")
    multi_channel_reconciliation_max_entries: int = Field(default=300, alias="MULTI_CHANNEL_RECONCILIATION_MAX_ENTRIES")
    multi_channel_reconciliation_max_time_delta_ms: int = Field(default=2000, alias="MULTI_CHANNEL_RECONCILIATION_MAX_TIME_DELTA_MS")
    multi_channel_reconciliation_min_pair_score: float = Field(default=0.45, alias="MULTI_CHANNEL_RECONCILIATION_MIN_PAIR_SCORE")
    multi_channel_reconciliation_match_score: float = Field(default=0.68, alias="MULTI_CHANNEL_RECONCILIATION_MATCH_SCORE")
    multi_channel_reconciliation_suggest_score: float = Field(default=0.78, alias="MULTI_CHANNEL_RECONCILIATION_SUGGEST_SCORE")
    multi_channel_reconciliation_ambiguity_delta: float = Field(default=0.08, alias="MULTI_CHANNEL_RECONCILIATION_AMBIGUITY_DELTA")
    multi_channel_reconciliation_refresh_ms: int = Field(default=750, alias="MULTI_CHANNEL_RECONCILIATION_REFRESH_MS")
    multi_channel_reconciliation_max_text_chars: int = Field(default=800, alias="MULTI_CHANNEL_RECONCILIATION_MAX_TEXT_CHARS")

    # Дерево общения (Conversation Tree): дебаунс live-LLM-экстрактора условий
    conversation_tree_debounce_ms: int = Field(default=35000, alias="CONVERSATION_TREE_DEBOUNCE_MS")
    conversation_tree_max_dialog_chars: int = Field(default=6000, alias="CONVERSATION_TREE_MAX_DIALOG_CHARS")

    # Production cutover (Этап 9.8): РУЧНОЕ продвижение конкретной встречи с single STT на
    # авторитетный multi-channel transcript. Single STT остаётся всегда-включённым hot standby.
    # Переключения источника моделируются «эпохами транскрипции»; нормализованные final
    # multi-channel сегменты сохраняются отдельно (без raw/PCM). Canary-rollout (по умолчанию
    # 0% + allowlist), kill switch, auto-fallback только при ЖЁСТКОМ сбое. По умолчанию ВЫКЛЮЧЕНО,
    # авто-promote отсутствует.
    multi_channel_cutover_enabled: bool = Field(default=False, alias="MULTI_CHANNEL_CUTOVER_ENABLED")
    multi_channel_cutover_rollout_percent: int = Field(default=0, alias="MULTI_CHANNEL_CUTOVER_ROLLOUT_PERCENT")
    multi_channel_cutover_allowlist_user_ids: str = Field(default="", alias="MULTI_CHANNEL_CUTOVER_ALLOWLIST_USER_IDS")
    multi_channel_cutover_allowlist_meeting_ids: str = Field(default="", alias="MULTI_CHANNEL_CUTOVER_ALLOWLIST_MEETING_IDS")
    multi_channel_cutover_require_quality_gate: bool = Field(default=True, alias="MULTI_CHANNEL_CUTOVER_REQUIRE_QUALITY_GATE")
    multi_channel_cutover_allow_force: bool = Field(default=True, alias="MULTI_CHANNEL_CUTOVER_ALLOW_FORCE")
    multi_channel_cutover_min_final_segments: int = Field(default=5, alias="MULTI_CHANNEL_CUTOVER_MIN_FINAL_SEGMENTS")
    multi_channel_cutover_min_match_ratio: float = Field(default=0.5, alias="MULTI_CHANNEL_CUTOVER_MIN_MATCH_RATIO")
    multi_channel_cutover_max_secondary_silence_ratio: float = Field(default=0.7, alias="MULTI_CHANNEL_CUTOVER_MAX_SECONDARY_SILENCE_RATIO")
    multi_channel_cutover_auto_fallback_on_failure: bool = Field(default=True, alias="MULTI_CHANNEL_CUTOVER_AUTO_FALLBACK_ON_FAILURE")
    multi_channel_cutover_boundary_dedupe_ms: int = Field(default=1500, alias="MULTI_CHANNEL_CUTOVER_BOUNDARY_DEDUPE_MS")
    multi_channel_cutover_boundary_dedupe_similarity: float = Field(default=0.6, alias="MULTI_CHANNEL_CUTOVER_BOUNDARY_DEDUPE_SIMILARITY")
    multi_channel_cutover_max_persisted_segments: int = Field(default=20000, alias="MULTI_CHANNEL_CUTOVER_MAX_PERSISTED_SEGMENTS")
    multi_channel_cutover_recent_minutes: int = Field(default=5, alias="MULTI_CHANNEL_CUTOVER_RECENT_MINUTES")
    multi_channel_cutover_max_transcript_chars: int = Field(default=120000, alias="MULTI_CHANNEL_CUTOVER_MAX_TRANSCRIPT_CHARS")

    @model_validator(mode="after")
    def _clamp_multi_channel_cutover(self):
        # Этап 9.8: rollout/quality/dedupe-параметры приводим к корректным диапазонам.
        self.multi_channel_cutover_rollout_percent = min(100, max(0, self.multi_channel_cutover_rollout_percent))
        self.multi_channel_cutover_min_final_segments = max(0, self.multi_channel_cutover_min_final_segments)
        self.multi_channel_cutover_min_match_ratio = min(1.0, max(0.0, self.multi_channel_cutover_min_match_ratio))
        self.multi_channel_cutover_max_secondary_silence_ratio = min(
            1.0, max(0.0, self.multi_channel_cutover_max_secondary_silence_ratio))
        self.multi_channel_cutover_boundary_dedupe_ms = max(0, self.multi_channel_cutover_boundary_dedupe_ms)
        self.multi_channel_cutover_boundary_dedupe_similarity = min(
            1.0, max(0.0, self.multi_channel_cutover_boundary_dedupe_similarity))
        self.multi_channel_cutover_max_persisted_segments = max(1, self.multi_channel_cutover_max_persisted_segments)
        self.multi_channel_cutover_recent_minutes = max(1, self.multi_channel_cutover_recent_minutes)
        self.multi_channel_cutover_max_transcript_chars = max(1000, self.multi_channel_cutover_max_transcript_chars)
        return self

    @staticmethod
    def _parse_int_csv(raw: str) -> set[int]:
        out: set[int] = set()
        for part in (raw or "").replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.add(int(part))
            except ValueError:
                continue
        return out

    @property
    def multi_channel_cutover_allowlist_user_ids_set(self) -> set[int]:
        return self._parse_int_csv(self.multi_channel_cutover_allowlist_user_ids)

    @property
    def multi_channel_cutover_allowlist_meeting_ids_set(self) -> set[int]:
        return self._parse_int_csv(self.multi_channel_cutover_allowlist_meeting_ids)

    document_max_extract_chars: int = Field(default=3_000_000, alias="DOCUMENT_MAX_EXTRACT_CHARS")
    s3_document_prefix: str = Field(default="documents", alias="S3_DOCUMENT_PREFIX")
    s3_extracted_text_prefix: str = Field(default="documents_extracted", alias="S3_EXTRACTED_TEXT_PREFIX")

    # Presigned S3 document upload — hardening (Этап 22). Наследует общий S3_* клиент/креды.
    # DOCUMENT_S3_UPLOAD_ENABLED — kill-switch поверх s3_enabled; default True, чтобы не ломать
    # прод (там presigned-документы уже активны при заданном S3_*). False → фронт уходит на legacy.
    document_storage_backend: str = Field(default="local", alias="DOCUMENT_STORAGE_BACKEND")
    document_s3_upload_enabled: bool = Field(default=True, alias="DOCUMENT_S3_UPLOAD_ENABLED")
    document_s3_prefix: str = Field(default="documents", alias="DOCUMENT_S3_PREFIX")
    document_s3_presign_expires_seconds: int = Field(default=900, alias="DOCUMENT_S3_PRESIGN_EXPIRES_SECONDS")
    document_s3_max_upload_bytes: int = Field(default=52_428_800, alias="DOCUMENT_S3_MAX_UPLOAD_BYTES")
    # Content-type allow-list. Расширен относительно спеки, чтобы покрыть ВСЕ разрешённые расширения
    # (xlsx/csv/md/doc/xls), иначе валидные загрузки отклонялись бы. Расширение — авторитетная проверка.
    document_s3_allowed_content_types: str = Field(
        default=(
            "application/pdf,text/plain,text/markdown,text/csv,"
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
            "application/msword,application/vnd.ms-excel"
        ),
        alias="DOCUMENT_S3_ALLOWED_CONTENT_TYPES",
    )
    document_s3_sse: str = Field(default="", alias="DOCUMENT_S3_SSE")
    document_s3_kms_key_id: str = Field(default="", alias="DOCUMENT_S3_KMS_KEY_ID")
    document_s3_complete_head_check_enabled: bool = Field(
        default=True, alias="DOCUMENT_S3_COMPLETE_HEAD_CHECK_ENABLED")
    # forward-compat: пусто = наследовать S3_* общего клиента; отдельный bucket/endpoint для
    # документов потребует раздельного boto3-клиента (не в этом этапе, чтобы не трогать batch).
    document_s3_bucket: str = Field(default="", alias="DOCUMENT_S3_BUCKET")
    document_s3_region: str = Field(default="", alias="DOCUMENT_S3_REGION")
    document_s3_endpoint_url: str = Field(default="", alias="DOCUMENT_S3_ENDPOINT_URL")
    document_s3_force_path_style: bool = Field(default=False, alias="DOCUMENT_S3_FORCE_PATH_STYLE")

    @model_validator(mode="after")
    def _clamp_multi_channel_export(self):
        # Этап 9.4: защитное приведение лимитов экспорта к корректным диапазонам
        # (без падения старта; невалидный env просто клампится).
        self.multi_channel_export_max_channels = min(8, max(1, self.multi_channel_export_max_channels))
        self.multi_channel_export_default_seconds = max(1, self.multi_channel_export_default_seconds)
        self.multi_channel_export_max_seconds = max(
            self.multi_channel_export_default_seconds, self.multi_channel_export_max_seconds
        )
        self.multi_channel_export_max_bytes = max(45, self.multi_channel_export_max_bytes)
        self.multi_channel_export_max_offset_ms = max(0, self.multi_channel_export_max_offset_ms)
        return self

    @model_validator(mode="after")
    def _clamp_multi_channel_live(self):
        # Этап 9.6: защитное приведение realtime-параметров к согласованным диапазонам.
        fm = max(1, self.multi_source_ingest_frame_ms)
        self.multi_channel_live_min_channels = max(2, self.multi_channel_live_min_channels)
        self.multi_channel_live_max_channels = min(8, max(self.multi_channel_live_min_channels,
                                                          self.multi_channel_live_max_channels))
        # send_chunk_ms кратен canonical frame_ms (минимум один кадр)
        self.multi_channel_live_send_chunk_ms = max(fm, (self.multi_channel_live_send_chunk_ms // fm) * fm)
        self.multi_channel_live_playout_delay_ms = max(fm, self.multi_channel_live_playout_delay_ms)
        self.multi_channel_live_min_prebuffer_ms = max(self.multi_channel_live_send_chunk_ms,
                                                       self.multi_channel_live_min_prebuffer_ms)
        self.multi_channel_live_send_queue_chunks = max(1, self.multi_channel_live_send_queue_chunks)
        self.multi_channel_live_start_timeout_seconds = max(1, self.multi_channel_live_start_timeout_seconds)
        self.multi_channel_live_close_timeout_seconds = max(1, self.multi_channel_live_close_timeout_seconds)
        self.multi_channel_live_keepalive_seconds = max(1, self.multi_channel_live_keepalive_seconds)
        self.multi_channel_live_max_global_sessions = min(8, max(1, self.multi_channel_live_max_global_sessions))
        self.multi_channel_live_silence_warn_ratio = min(1.0, max(0.0, self.multi_channel_live_silence_warn_ratio))
        return self

    @model_validator(mode="after")
    def _clamp_multi_channel_reconciliation(self):
        # Этап 9.7: согласованные пороги/лимиты сопоставления.
        self.multi_channel_reconciliation_max_primary_segments = max(1, self.multi_channel_reconciliation_max_primary_segments)
        self.multi_channel_reconciliation_max_candidate_segments = max(1, self.multi_channel_reconciliation_max_candidate_segments)
        self.multi_channel_reconciliation_max_entries = max(1, self.multi_channel_reconciliation_max_entries)
        self.multi_channel_reconciliation_max_time_delta_ms = max(1, self.multi_channel_reconciliation_max_time_delta_ms)
        # пороги в [0,1] и монотонны: min_pair <= match <= suggest
        mp = min(1.0, max(0.0, self.multi_channel_reconciliation_min_pair_score))
        mt = min(1.0, max(mp, self.multi_channel_reconciliation_match_score))
        sg = min(1.0, max(mt, self.multi_channel_reconciliation_suggest_score))
        self.multi_channel_reconciliation_min_pair_score = mp
        self.multi_channel_reconciliation_match_score = mt
        self.multi_channel_reconciliation_suggest_score = sg
        self.multi_channel_reconciliation_ambiguity_delta = min(0.5, max(0.0, self.multi_channel_reconciliation_ambiguity_delta))
        self.multi_channel_reconciliation_refresh_ms = max(100, self.multi_channel_reconciliation_refresh_ms)
        self.multi_channel_reconciliation_max_text_chars = min(5000, max(100, self.multi_channel_reconciliation_max_text_chars))
        # дерево общения: дебаунс не реже 5с (защита от спама LLM), окно диалога — разумный предел
        self.conversation_tree_debounce_ms = max(5000, self.conversation_tree_debounce_ms)
        self.conversation_tree_max_dialog_chars = min(20000, max(1000, self.conversation_tree_max_dialog_chars))
        return self

    @property
    def s3_enabled(self) -> bool:
        return bool(self.s3_endpoint and self.s3_bucket and self.s3_access_key and self.s3_secret_key)

    @property
    def document_allowed_extensions_set(self) -> set[str]:
        return {e.strip().lower() for e in self.document_allowed_extensions.split(",") if e.strip()}

    @property
    def document_s3_upload_active(self) -> bool:
        """Presigned-S3 путь для документов активен (S3 сконфигурирован И kill-switch включён)."""
        return bool(self.s3_enabled and self.document_s3_upload_enabled)

    @property
    def document_s3_allowed_content_types_set(self) -> set[str]:
        return {c.strip().lower() for c in self.document_s3_allowed_content_types.split(",") if c.strip()}

    @property
    def document_s3_prefix_effective(self) -> str:
        return (self.document_s3_prefix or self.s3_document_prefix or "documents").strip()

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
            "secondary_audio_shadow_enabled": self.secondary_audio_shadow_enabled,
            "secondary_audio_shadow_max_devices": self.secondary_audio_shadow_max_devices,
            "secondary_audio_shadow_target_sample_rate": self.secondary_audio_shadow_target_sample_rate,
            "multi_source_ingest_enabled": self.multi_source_ingest_enabled,
            "multi_source_ingest_frame_ms": self.multi_source_ingest_frame_ms,
            "multi_source_ingest_max_tracks": self.multi_source_ingest_max_tracks,
            "multi_channel_export_enabled": self.multi_channel_export_enabled,
            "multi_channel_export_max_channels": self.multi_channel_export_max_channels,
            "multi_channel_export_max_seconds": self.multi_channel_export_max_seconds,
            "multi_channel_export_max_bytes": self.multi_channel_export_max_bytes,
            "multi_channel_batch_stt_enabled": self.multi_channel_batch_stt_enabled,
            "multi_channel_batch_stt_provider": self.multi_channel_batch_stt_provider,
            "multi_channel_batch_stt_model": self.multi_channel_batch_stt_model,
            "multi_channel_batch_stt_max_channels": self.multi_channel_batch_stt_max_channels,
            "multi_channel_batch_stt_max_seconds": self.multi_channel_batch_stt_max_seconds,
            "multi_channel_batch_stt_max_wav_bytes": self.multi_channel_batch_stt_max_wav_bytes,
            "multi_channel_live_enabled": self.multi_channel_live_enabled,
            "multi_channel_live_provider": self.multi_channel_live_provider,
            "multi_channel_live_model": self.multi_channel_live_model,
            "multi_channel_live_max_channels": self.multi_channel_live_max_channels,
            "multi_channel_live_max_global_sessions": self.multi_channel_live_max_global_sessions,
            "multi_channel_reconciliation_enabled": self.multi_channel_reconciliation_enabled,
            "multi_channel_reconciliation_max_entries": self.multi_channel_reconciliation_max_entries,
            "multi_channel_reconciliation_match_score": self.multi_channel_reconciliation_match_score,
            "multi_channel_reconciliation_suggest_score": self.multi_channel_reconciliation_suggest_score,
            "multi_channel_cutover_enabled": self.multi_channel_cutover_enabled,
            "multi_channel_cutover_rollout_percent": self.multi_channel_cutover_rollout_percent,
            "multi_channel_cutover_allowlist_user_count": len(self.multi_channel_cutover_allowlist_user_ids_set),
            "multi_channel_cutover_allowlist_meeting_count": len(self.multi_channel_cutover_allowlist_meeting_ids_set),
            "multi_channel_cutover_require_quality_gate": self.multi_channel_cutover_require_quality_gate,
            "multi_channel_cutover_auto_fallback_on_failure": self.multi_channel_cutover_auto_fallback_on_failure,
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
