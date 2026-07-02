"""Per-user meeting session manager.

Manages transcription, AI hints, audio recording, and batch finalization.
Each user gets their own SessionManager with independent state.
"""

import asyncio
import json
import logging
import random
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Callable, Any

from ..config import get_settings
from ..core.context.analyzer import ContextAnalyzer
from ..core.context.document_loader import DocumentLoader
from ..core.context.knowledge_base import get_arguments_for_keyword
from ..core.llm.client import LLMClient
from ..core.llm.prompt_context_builder import PromptContextBuilder
from ..core.llm.prompts import PromptBuilder
from ..core.transcription.models import (
    TranscriptSegment, CommittedSegment, PartialTranscript,
    UNKNOWN_SPEAKER, SegmentOrigin,
)
from ..core.context.event_detector import EventDetector
from ..core.context.signal_engine import SignalEngine
from ..core.context.signal_policy import (
    resolve_signal_runtime_config, evaluate_signal_decision,
)
from ..core.context.signal_trace import build_signal_trace_event, log_signal_trace
from ..core.context.audio_capture_metadata import (
    AudioCaptureMetadata, parse_audio_capture_metadata,
)
from ..core.context.multichannel_shadow_state import AudioMultichannelShadowIngest
from ..core.context.audio_frame_v2 import parse_audio_frame_v2
from ..core.context.per_channel_stt_policy import resolve_per_channel_stt_runtime_config
from ..core.context.per_channel_stt_trace import (
    build_per_channel_stt_trace_event, log_per_channel_stt_trace,
)
from ..core.audio.per_channel_stt import PerChannelSttPipeline
from .speaker_identity_service import SpeakerIdentityService
from ..core.context.speaker_audio_links import (
    extract_audio_links_from_metadata, build_speaker_audio_link_map,
)
from ..core.context.speaker_audio_attribution import (
    SpeakerAudioAttributionTracker, extract_speaker_audio_observations_from_payload,
)
from ..core.context.segment_source_attribution import (
    build_observation_payload_from_segment,
    build_segment_source_attribution_dict,
    attach_source_attribution_to_committed_segment,
)
from ..core.context.source_attribution_reconciler import (
    SourceAttributionReconciler, extract_source_candidate_from_payload,
)
from ..core.context.source_attribution_policy import (
    resolve_source_reconcile_runtime_config, evaluate_source_reconcile_decision,
)
from ..core.context.source_reconcile_trace import (
    build_source_reconcile_trace_event, log_source_reconcile_trace,
)
from ..core.context.meeting_memory import MeetingMemory
from ..core.llm.suggestion_prompts import (
    build_auto_cards_prompt, build_auto_cards_prompt_from_signal,
    build_manual_cards_prompt, build_strengthen_prompt,
)
from .context_pack import assemble_live_context_pack
from ..core.transcription.turn_assembler import TurnAssembler
from .audio_recorder import AudioRecorder
from .suggestion_parser import parse_suggestion_response, apply_safety_checks, fallback_response
from .ai_settings import mode_tokens as _mode_tokens

logger = logging.getLogger("meridian.session")

# Global registry of active sessions
_sessions: Dict[int, "SessionManager"] = {}

# AI hint debounce settings
HINT_DEBOUNCE_SEC = 3.0
HINT_COOLDOWN_SEC = 30.0
MIN_SEGMENTS_FOR_HINT = 2

# Speaker side labels for prompt annotation. Диаризация v1 — две стороны: «Мы»/«Не мы».
# ally/third_party — legacy fallback (старые записи) → сводятся к тем же двум сторонам.
ROLE_LABELS = {
    "self": "МЫ",
    "opponent": "НЕ МЫ",
    "ally": "МЫ",            # legacy fallback
    "third_party": "НЕ МЫ",  # legacy fallback
}

# Keyword → analysis status message (defaults)
DEFAULT_KEYWORD_STATUS = {
    "цена": "Анализирую возражение по цене...",
    "срок": "Анализирую обсуждение сроков...",
    "гарантия": "Анализирую вопрос гарантий...",
    "штраф": "Анализирую вопрос штрафных санкций...",
    "договор": "Анализирую обсуждение договора...",
    "обсуждаем": "Анализирую текущую тему...",
    "ваше мнение": "Анализирую запрос мнения...",
    "смета": "Анализирую обсуждение сметы...",
    "аванс": "Анализирую вопрос авансирования...",
    "материалы": "Анализирую обсуждение материалов...",
}

DEFAULT_VALID_SUGGESTION_TYPES = {"priority", "counter", "question", "risk"}


def get_session_manager(user_id: int) -> "SessionManager":
    """Get or create a session manager for a user."""
    if user_id not in _sessions:
        _sessions[user_id] = SessionManager(user_id)
    return _sessions[user_id]


def remove_session_manager(user_id: int):
    """Remove and cleanup a user's session."""
    session = _sessions.pop(user_id, None)
    if session:
        session.cleanup()


def cleanup_idle_sessions(max_idle: float = 3600) -> int:
    """Remove sessions idle longer than max_idle seconds. Skip listening sessions."""
    now = time.time()
    to_remove = [
        uid for uid, s in _sessions.items()
        if now - s.last_activity > max_idle and not s.is_listening
    ]
    for uid in to_remove:
        logger.info("[SessionCleanup] removing idle session user=%d", uid)
        remove_session_manager(uid)
    return len(to_remove)


class SessionManager:
    """Manages a single user's meeting session state."""

    def __init__(self, user_id: int):
        self.user_id = user_id

        # Core components
        self.context_analyzer = ContextAnalyzer()
        self.document_loader = DocumentLoader()
        self.prompt_builder = PromptBuilder()
        self.role_data: dict | None = None

        # LLM client (initialized when API keys are available)
        self.llm_client: Optional[LLMClient] = None

        # Transcription service (created on start_listening)
        self.transcription_service = None
        self.audio_queue: Optional[asyncio.Queue] = None

        # Audio recorder for batch finalization
        self.audio_recorder: Optional[AudioRecorder] = None
        self._session_id: Optional[str] = None
        self.db_session_id: Optional[int] = None
        self.negotiation_type: str = "sale"
        self.meeting_role: str = ""
        self.opponent_weaknesses: str = ""
        self.meeting_title: str = ""

        # State
        self.last_activity: float = time.time()
        self.is_listening = False
        self._transcription_task: Optional[asyncio.Task] = None
        # Этап 9.8: server-эпоха старта primary STT-стрима — якорь speech-time меток
        # committed-сегментов (provider даёт относительные start/end). None до start_listening.
        self.listening_started_server_ms: Optional[int] = None
        # Длительность последнего завершённого интервала записи (сек) — для инкрементального
        # персиста recorded_seconds. Выставляется в stop_listening, читается комнатой.
        self.last_interval_seconds: int = 0
        # Этап 9.8: провайдер авторитетного транскрипта (multi-channel epoch). None → single.
        self._authoritative_context_provider: Optional[Callable] = None

        # Committed segment store (source of truth during live session)
        self._committed_segments: List[CommittedSegment] = []

        # AI hint debounce
        self._hint_buffer: List[CommittedSegment] = []
        self._hint_debounce_task: Optional[asyncio.Task] = None
        self._auto_trigger_cooldown: Dict[str, float] = {}

        # Speaker
        self.speaker_mapping: Dict[str, str] = {}
        self.current_speaker: Optional[str] = None
        self.speaker_roles: Dict[str, str] = {}  # speaker_label → side
        self.speaker_names: Dict[str, str] = {}  # speaker_label → имя (display_name)
        # Этап 8: segment-level коррекции диаризации (segment_id → {side, corrected_speaker_label})
        self.speaker_segment_corrections: Dict[str, dict] = {}
        # Этап 6: structured speaker↔audio link (speaker_label → source_id / channel_label).
        # Пусто по умолчанию; заполняется set_speaker_audio_metadata() (см. TODO ниже).
        self.speaker_audio_source_map: Dict[str, str] = {}   # speaker_label → audio source id
        self.speaker_channel_map: Dict[str, str] = {}        # speaker_label → channel label
        # Этап 15: безопасная audio capture route metadata (техническая зона записи, НЕ сторона).
        # Диагностика/телеметрия; НЕ создаёт source attribution и НЕ задаёт speaker_identity_hints.
        self._audio_capture_metadata: Optional[AudioCaptureMetadata] = None
        # Этап 16: channel-aware v2 shadow ingest (только агрегаты; не STT/не attribution/не сторона).
        self._multichannel_shadow_ingest = AudioMultichannelShadowIngest()
        self._mc_shadow_log_every = 50  # лог не на каждый кадр
        # Этап 17: per-channel STT canary (opt-in, по умолчанию выкл/shadow). Не заменяет legacy STT.
        self._per_channel_stt_pipeline: Optional[PerChannelSttPipeline] = None
        self._per_channel_stt_adapter = None  # явная инъекция (тесты); None → строим по provider
        self._per_channel_stt_provider_key = None  # (provider, model_id, language_code) для rebuild
        self._per_channel_stt_semaphore: Optional[asyncio.Semaphore] = None
        self._per_channel_stt_sem_size = 0
        self._per_channel_stt_tasks: set = set()

        # Stored API keys for batch finalization
        self._elevenlabs_key: Optional[str] = None

        # Custom suggestion types / trigger keywords (per-user overrides)
        self._valid_suggestion_types = set(DEFAULT_VALID_SUGGESTION_TYPES)
        self._keyword_status = dict(DEFAULT_KEYWORD_STATUS)

        # Turn assembler (merges consecutive same-speaker segments)
        self._turn_assembler = TurnAssembler()

        # Meeting memory (three-layer context for long meetings)
        self._meeting_memory = MeetingMemory()

        # Event detector (rule-based negotiation events) — legacy fallback
        self._event_detector = EventDetector()

        # Signal Engine (Этап 1): контекстная классификация переговорной ситуации
        self._signal_engine = SignalEngine()

        # Speaker Identity Graph v1 (Этап 4): нормализация ролей/сторон спикеров
        self._speaker_identity_service = SpeakerIdentityService()

        # Этап 7: live speaker→audio attribution (link только при устойчивой attribution)
        self._speaker_audio_attribution = SpeakerAudioAttributionTracker()

        # Этап 10: reconciliation source candidate (source/channel) ↔ committed segment (speaker_label)
        self._source_attribution_reconciler = SourceAttributionReconciler()
        # Этап 11: аккумуляторы решений reconcile для SIGNAL_ENGINE_TRACE (агрегаты, без raw)
        self._reconcile_would_attach = 0
        self._reconcile_actual_attach = 0
        self._reconcile_decision_reasons: Dict[str, int] = {}
        self._reconcile_last_shadow: Optional[bool] = None

        # Prompt context builder (unified context assembly for 3 modes)
        self._ctx_builder = PromptContextBuilder(
            meeting_memory=self._meeting_memory,
            document_loader=self.document_loader,
            context_analyzer=self.context_analyzer,
            committed_context_fn=self._get_committed_context,
            speaker_roles_fn=lambda: self.speaker_roles,
            authoritative_context_fn=self._call_authoritative_provider,
        )

        # WebSocket send callback
        self._ws_send: Optional[Callable] = None

        # Conversation Tree: хук на committed-сегмент (fn(segment, role) -> awaitable).
        # Ставит MeetingRoom (есть доступ к БД). Fire-and-forget, не блокирует STT.
        self._committed_hook: Optional[Callable] = None

        # Этап 4: провайдер контекста документов встречи (DB-backed), async(meeting_id, query)->str
        self._doc_context_provider: Optional[Callable] = None

        # Этап 7: провайдер утверждённой базы знаний, async(meeting_id, query)->str
        self._knowledge_provider: Optional[Callable] = None

        # Этап 8: провайдер итогов выбранных прошлых встреч, async(meeting_id, query)->str
        self._previous_meetings_provider: Optional[Callable] = None

        # Этап 5 (RAG): провайдер фрагментов подключённых RAG-папок, async(meeting_id, query)->str
        self._rag_context_provider: Optional[Callable] = None

        # Письма PayHub (внешний RAG): провайдер блока переписки, async(meeting_id, query)->str
        self._letters_context_provider: Optional[Callable] = None

        # Этап 9: resolved AI-настройки встречи (None → fallback на глобальный config)
        self.ai_settings: Optional[dict] = None
        self._llm_api_key: Optional[str] = None
        self._llm_temperature: float = 0.7
        self._model_clients: Dict[str, LLMClient] = {}

    def touch(self):
        """Update last activity timestamp."""
        self.last_activity = time.time()

    def set_ws_send(self, send_func: Callable):
        """Set WebSocket send function for pushing messages to client."""
        self._ws_send = send_func

    def set_committed_hook(self, hook: Callable):
        """Conversation Tree: колбэк на committed-сегмент, async(segment, role)."""
        self._committed_hook = hook

    def set_authoritative_transcript_provider(self, provider: Optional[Callable]):
        """Этап 9.8: провайдер авторитетного транскрипта, fn(recent: bool) -> str|None.

        None или возврат None → single (committed path без изменений); строка → multi epoch.
        """
        self._authoritative_context_provider = provider

    def _call_authoritative_provider(self, recent: bool):
        if self._authoritative_context_provider is None:
            return None
        try:
            return self._authoritative_context_provider(recent)
        except Exception:
            return None

    def set_speaker_segment_corrections(self, corrections: Dict[str, dict]) -> None:
        """Заменить in-memory кэш segment-level коррекций (segment_id → {side, corrected_speaker_label})."""
        self.speaker_segment_corrections = corrections or {}

    def _resolve_segment(self, segment) -> tuple[str, str | None]:
        """(effective_speaker_label, side) реплики с учётом segment-level коррекций.

        Приоритет стороны: коррекция реплики → роль corrected_label → роль original_label.
        """
        from .speaker_roles import to_public_side  # локальный импорт: избегаем цикла
        original = (getattr(segment, "speaker_label", None) or getattr(segment, "speaker_id", None)
                    or getattr(segment, "speaker", None) or "")
        seg_key = getattr(segment, "segment_id", None) or ""
        corr = self.speaker_segment_corrections.get(seg_key) if seg_key else None
        corrected_label = (corr or {}).get("corrected_speaker_label")
        # Глобальное имя спикера (если задано) подменяет сырую метку SM_0/DG_S0
        effective = corrected_label or self.speaker_names.get(original) or original
        side = None
        if corr and corr.get("side"):
            side = to_public_side(corr.get("side"))
        if side is None and corrected_label:
            side = to_public_side(self.speaker_roles.get(corrected_label))
        if side is None and original:
            side = to_public_side(self.speaker_roles.get(original))
        return effective, side

    def _fire_committed_hook(self, segment) -> None:
        """Fire-and-forget вызов committed-хука. Ошибки не должны ломать пайплайн."""
        if not self._committed_hook:
            return
        _speaker, role = self._resolve_segment(segment)  # segment-level коррекция стороны
        try:
            asyncio.create_task(self._committed_hook(segment, role))
        except Exception:
            pass

    def set_doc_context_provider(self, provider: Callable):
        """Этап 4: провайдер релевантных фрагментов документов встречи из БД."""
        self._doc_context_provider = provider

    def set_knowledge_provider(self, provider: Callable):
        """Этап 7: провайдер утверждённой базы знаний (approved-элементы в scope встречи)."""
        self._knowledge_provider = provider

    async def _knowledge_block(self, query_text: str = "") -> str:
        """Блок утверждённой базы знаний для подсказок (или '')."""
        if not self._ai("knowledge_context_enabled", True):
            return ""  # Этап 9: база знаний выключена в настройках
        if not self._knowledge_provider or not self.db_session_id:
            return ""
        try:
            return await self._knowledge_provider(self.db_session_id, query_text or "")
        except Exception:
            return ""

    def set_previous_meetings_provider(self, provider: Callable):
        """Этап 8: провайдер компактных итогов выбранных прошлых встреч."""
        self._previous_meetings_provider = provider

    async def _previous_meetings_block(self, query_text: str = "") -> str:
        """Блок «ПРЕДЫДУЩИЕ ВСТРЕЧИ…» для подсказок (или '')."""
        if not self._ai("previous_meetings_context_enabled", True):
            return ""  # Этап 9: контекст прошлых встреч выключен в настройках
        if not self._previous_meetings_provider or not self.db_session_id:
            return ""
        try:
            return await self._previous_meetings_provider(self.db_session_id, query_text or "")
        except Exception:
            return ""

    def set_rag_context_provider(self, provider: Callable):
        """Этап 5: провайдер фрагментов подключённых RAG-папок встречи."""
        self._rag_context_provider = provider

    async def _rag_context_block(self, query_text: str = "") -> str:
        """Блок «Релевантные фрагменты RAG-папок» (или '').

        Этап 6: отдельный блок ContextPack (больше НЕ внутри document slot).
        v1 зависит от document_context_enabled + глобального rag_context_enabled.
        """
        if not getattr(get_settings(), "rag_context_enabled", True):
            return ""  # RAG выключен глобально в конфиге
        if not self._ai("document_context_enabled", True):
            return ""  # документы (и RAG как их часть v1) выключены в настройках
        if not self._rag_context_provider or not self.db_session_id:
            return ""
        try:
            return await self._rag_context_provider(self.db_session_id, query_text or "")
        except Exception:
            return ""

    def set_letters_context_provider(self, provider: Callable):
        """Письма PayHub: провайдер блока переписки (внешний RAG), отдельный от RAG-папок."""
        self._letters_context_provider = provider

    async def _letters_context_block(self, query_text: str = "") -> str:
        """Блок «Переписка (письма)» (или '').

        Гейт: глобальная доступность PayHub-RAG + per-meeting AI-тогл. Никогда не падает.
        """
        if not get_settings().letters_rag_effective_enabled:
            return ""  # письма не настроены/выключены глобально
        if not self._ai("letters_context_enabled", True):
            return ""  # письма выключены в настройках встречи
        if not self._letters_context_provider or not self.db_session_id:
            return ""
        try:
            return await self._letters_context_provider(self.db_session_id, query_text or "")
        except Exception:
            return ""

    async def _augment_doc_context(self, base: str, query_text: str) -> str:
        """Документы встречи из БД (in-memory loader base + DB-провайдер).

        Этап 6: отвечает ТОЛЬКО за документы; RAG — отдельный блок ContextPack.
        """
        if not self._ai("document_context_enabled", True):
            return base  # Этап 9: документы выключены в настройках
        if not self._doc_context_provider or not self.db_session_id:
            return base
        try:
            db_block = await self._doc_context_provider(self.db_session_id, query_text or "")
        except Exception:
            db_block = ""
        if db_block and base:
            return f"{base}\n\n{db_block}"
        return db_block or base

    def _trace_pack(self, pack, mode: str) -> None:
        """Короткая телеметрия Context Pack (без полного контента)."""
        if not get_settings().context_pack_trace_enabled:
            return
        summary = [(b.kind, len(b.content), b.enabled, b.truncated) for b in pack.blocks]
        logger.info(
            "context_pack mode=%s meeting=%s total_chars=%s blocks=%s truncated=%s",
            mode, self.db_session_id, pack.total_chars, summary, pack.truncated,
        )

    async def _build_context_pack_for_prompt(
        self, *, mode: str, query_text: str, meeting_context_block: str,
        recent_dialog: str = "", full_transcript: str = "",
        document_context: str = "", document_already_augmented: bool = False,
    ):
        """Единая сборка ContextPack из провайдеров для live-подсказок.

        document_already_augmented=True — base уже прошёл _augment_doc_context (auto-путь),
        чтобы не augment-ить документы дважды.
        """
        db_doc = (document_context if document_already_augmented
                  else await self._augment_doc_context(document_context, query_text))
        rag = await self._rag_context_block(query_text)
        letters = await self._letters_context_block(query_text)
        knowledge = await self._knowledge_block(query_text)
        previous = await self._previous_meetings_block(query_text)
        pack = assemble_live_context_pack(
            mode=mode, query_text=query_text,
            meeting_context_block=meeting_context_block,
            recent_dialog=recent_dialog, full_transcript=full_transcript,
            document_context=db_doc, rag_context=rag, letters_context=letters,
            knowledge_context=knowledge, previous_meetings_context=previous,
            ai_settings=self.ai_settings,
        )
        self._trace_pack(pack, mode)
        return pack

    def configure_llm(self, api_key: str, model: str, temperature: float):
        """Configure LLM client with API key from database."""
        self._llm_api_key = api_key
        self._llm_temperature = temperature
        self.llm_client = LLMClient(
            api_key=api_key, model=model, temperature=temperature
        )
        self._model_clients = {model: self.llm_client}
        # Apply role system prompt if role was set before LLM
        if self.role_data and self.llm_client:
            self.llm_client.set_system_prompt(self.prompt_builder.system_prompt)

    # ---------------------------------------------------------------
    # Этап 9: resolved AI-настройки
    # ---------------------------------------------------------------

    def set_ai_settings(self, resolved: dict | None):
        """Применить resolved-настройки встречи (snapshot). Безопасно во время live."""
        if not resolved:
            return
        self.ai_settings = resolved
        live_model = resolved.get("live_suggestion_model")
        if live_model and self.llm_client and getattr(self.llm_client, "model", None) != live_model:
            # пересоздать основной клиент под новую live-модель, сохранив system prompt
            self.configure_llm(self._llm_api_key or "", live_model, self._llm_temperature)

    def _ai(self, key: str, default):
        if self.ai_settings is not None and self.ai_settings.get(key) is not None:
            return self.ai_settings.get(key)
        return default

    def _mode(self) -> str:
        return self._ai("mode", "balanced")

    def _client_for_model(self, model: str | None) -> LLMClient:
        """LLM-клиент для конкретной модели (кэш). Fallback — основной клиент."""
        if not model or not self._llm_api_key:
            return self.llm_client
        if getattr(self.llm_client, "model", None) == model:
            return self.llm_client
        client = self._model_clients.get(model)
        if client is None:
            client = LLMClient(api_key=self._llm_api_key, model=model, temperature=self._llm_temperature)
            if self.role_data:
                client.set_system_prompt(self.prompt_builder.system_prompt)
            self._model_clients[model] = client
        return client

    def set_role(self, role_data: dict):
        """Set negotiation role — rebuilds prompts and system prompt."""
        self.role_data = role_data
        self.prompt_builder = PromptBuilder(role_data=role_data)
        if self.llm_client:
            self.llm_client.set_system_prompt(self.prompt_builder.system_prompt)

    def set_custom_suggestion_types(self, types: list[dict] | None):
        """Override suggestion types from user settings."""
        if not types:
            return
        enabled = [t for t in types if t.get("enabled", True)]
        if enabled:
            self._valid_suggestion_types = {t["key"] for t in enabled}
            self.prompt_builder.set_custom_suggestion_types(enabled)

    def set_custom_trigger_keywords(self, keywords: list[dict] | None):
        """Override trigger keywords from user settings."""
        if not keywords:
            return
        self._keyword_status = {}
        kw_list = []
        for kw in keywords:
            if kw.get("enabled", True):
                self._keyword_status[kw["keyword"]] = kw["status_message"]
                kw_list.append(kw["keyword"])
        if kw_list:
            self.context_analyzer.trigger_keywords = kw_list

    # ---------------------------------------------------------------
    # Listening lifecycle
    # ---------------------------------------------------------------

    async def start_listening(self, stt_provider: str, api_keys: dict,
                              diarization: bool = True, max_speakers: int = 3):
        """Start transcription with given provider and API keys."""
        if self.is_listening:
            return

        self.audio_queue = asyncio.Queue()
        self.is_listening = True
        self._session_id = uuid.uuid4().hex[:12]
        # Этап 9.8: якорь speech-time (момент старта стрима в server epoch ms)
        self.listening_started_server_ms = int(time.time() * 1000)

        # Store ElevenLabs key for batch finalization
        self._elevenlabs_key = api_keys.get("elevenlabs", "")

        # Create audio recorder
        settings = get_settings()
        recordings_dir = Path(settings.upload_dir) / "recordings" / str(self.user_id)
        self.audio_recorder = AudioRecorder(
            output_dir=recordings_dir,
            session_id=self._session_id,
        )
        self.audio_recorder.start()

        # Create transcription service based on provider
        service = self._build_transcription_service(
            stt_provider, api_keys, diarization, max_speakers
        )
        if service is None:
            await self._send_error(f"Unknown STT provider: {stt_provider}")
            self.is_listening = False
            return
        self.transcription_service = service

        # Start transcription in background task
        self._transcription_task = asyncio.create_task(
            self.transcription_service.run()
        )
        await self._send_status("Прослушивание активно...")

    def _build_transcription_service(self, stt_provider: str, api_keys: dict,
                                     diarization: bool, max_speakers: int):
        """Собрать STT-сервис по провайдеру (использует текущий self.audio_queue).

        Общий код для start_listening и restart_transcription. Возвращает None для
        неизвестного провайдера.
        """
        if stt_provider == "deepgram":
            from ..core.transcription.deepgram_streaming_service import (
                DeepgramStreamingTranscriptionService,
            )
            return DeepgramStreamingTranscriptionService(
                api_key=api_keys.get("deepgram", ""),
                audio_queue=self.audio_queue,
                message_callback=self._on_legacy_transcript,
                diarization=diarization,
            )
        if stt_provider == "elevenlabs":
            from ..core.transcription.streaming_service import (
                StreamingTranscriptionService,
            )
            return StreamingTranscriptionService(
                api_key=api_keys.get("elevenlabs", ""),
                audio_queue=self.audio_queue,
                on_partial=self._on_partial,
                on_committed=self._on_committed,
                on_error=self._on_stt_error,
                audio_recorder=self.audio_recorder,
            )
        if stt_provider == "speechmatics":
            from ..core.transcription.speechmatics_streaming_service import (
                SpeechmaticsStreamingTranscriptionService,
            )
            return SpeechmaticsStreamingTranscriptionService(
                api_key=api_keys.get("speechmatics", ""),
                audio_queue=self.audio_queue,
                message_callback=self._on_legacy_transcript,
                max_speakers=max_speakers,
            )
        return None

    async def restart_transcription(self, stt_provider: str, api_keys: dict,
                                    diarization: bool = True, max_speakers: int = 3) -> bool:
        """Пересоздать STT-сервис с новым max_speakers БЕЗ потери транскрипта.

        Нужно для Speechmatics: max_speakers вшивается в StartRecognition и меняется
        только новым подключением. Пересоздаём лишь сервис+задачу+очередь; committed-
        сегменты, turns, память, спикеры и якорь speech-time сохраняются.
        """
        if not self.is_listening:
            return False
        # teardown только STT-сервиса и его задачи (стейт транскрипта не трогаем)
        if self.transcription_service:
            self.transcription_service.stop()
        if self._transcription_task:
            self._transcription_task.cancel()
            try:
                await self._transcription_task
            except asyncio.CancelledError:
                pass
        # свежая очередь + новый сервис (is_listening остаётся True)
        self.audio_queue = asyncio.Queue()
        service = self._build_transcription_service(
            stt_provider, api_keys, diarization, max_speakers
        )
        if service is None:
            return False
        self.transcription_service = service
        self._transcription_task = asyncio.create_task(
            self.transcription_service.run()
        )
        await self._send_status("Распознавание перезапущено (число спикеров обновлено)")
        return True

    async def stop_listening(self):
        """Stop transcription and audio recording."""
        if not self.is_listening:
            return

        self.is_listening = False

        # Длительность интервала записи (старт→стоп) для инкремента recorded_seconds.
        if self.listening_started_server_ms is not None:
            self.last_interval_seconds = max(
                0, round((time.time() * 1000 - self.listening_started_server_ms) / 1000)
            )
            self.listening_started_server_ms = None
        else:
            self.last_interval_seconds = 0

        if self.transcription_service:
            self.transcription_service.stop()
        if self._transcription_task:
            self._transcription_task.cancel()
            try:
                await self._transcription_task
            except asyncio.CancelledError:
                pass

        self.transcription_service = None
        self.audio_queue = None

        # Stop audio recording (file stays on disk for batch)
        if self.audio_recorder:
            self.audio_recorder.stop()

        # Cancel pending hint check
        if self._hint_debounce_task and not self._hint_debounce_task.done():
            self._hint_debounce_task.cancel()

        # Этап 17: дождаться in-flight per-channel STT задач, чтобы они не пережили teardown сессии.
        await self.drain_per_channel_stt_tasks()

        await self._send_status("Прослушивание остановлено")

    # ---------------------------------------------------------------
    # ElevenLabs callbacks (new: type-separated)
    # ---------------------------------------------------------------

    def _on_partial(self, partial: PartialTranscript):
        """Partial transcript — UI preview only. NO storage, NO analysis."""
        if self._ws_send:
            asyncio.create_task(self._send_json({
                "type": "transcript",
                **partial.to_wire(),
            }))

    def _on_committed(self, segment: CommittedSegment):
        """Committed segment — source of truth. Store, analyze, notify."""
        # Apply speaker label
        if segment.speaker_id in self.speaker_mapping:
            segment.speaker_label = self.speaker_mapping[segment.speaker_id]
        elif self.current_speaker:
            segment.speaker_label = self.current_speaker

        # Этап 9.8: speech-time метки (для атрибуции эпох) — момент речи, не прихода события
        segment.assign_speech_timestamps(self.listening_started_server_ms)

        # Этап 10: попытка reconcile committed segment (speaker_label) с накопленным isolated
        # source candidate (source/channel). Проставит source_attribution ДО committed-hook, если
        # есть сильный НЕ-ambiguous match. Без кандидатов / при общем room-mic — no-op (прежнее
        # поведение). Кандидаты копит observe_source_attribution_candidate (из MeetingRoom/ctx).
        # Сторона здесь НЕ выводится; bridge/manual source_attribution не перезаписывается.
        self.reconcile_source_attribution_for_segment(segment)

        # Store committed segment
        self._committed_segments.append(segment)

        # Add to context analyzer (committed only)
        self.context_analyzer.add_segment(segment.to_legacy())

        # Send committed_transcript with word-level data to client
        # (frontend handles this in committed_transcript case,
        #  which adds to both committedSegments and messages)
        if self._ws_send:
            asyncio.create_task(self._send_json({
                "type": "committed_transcript",
                **segment.to_wire_full(),
            }))

        # Update turn assembler and send turn_update
        speaker = segment.speaker_label or segment.speaker_id
        turn, _ = self._turn_assembler.push(
            speaker=speaker,
            text=segment.text,
            start_time=segment.start_time,
            end_time=segment.end_time,
            wall_clock=segment.wall_clock,
        )
        if self._ws_send:
            asyncio.create_task(self._send_turn_update(turn))

        # Feed meeting memory
        self._meeting_memory.ingest_turn(turn)
        if self._meeting_memory.needs_summary_update() and self.llm_client:
            asyncio.create_task(self._meeting_memory.update_summary(self.llm_client))

        # Schedule debounced AI hint check
        self._schedule_hint_check(segment)

        # Conversation Tree: обновить дерево общения (fire-and-forget)
        self._fire_committed_hook(segment)

    def _on_stt_error(self, error_type: str, error_msg: str):
        """Handle STT error events."""
        if self._ws_send:
            asyncio.create_task(self._send_error(
                f"STT ошибка [{error_type}]: {error_msg}"
            ))

    # ---------------------------------------------------------------
    # Legacy callback (Deepgram / Gemini backward compat)
    # ---------------------------------------------------------------

    def _legacy_to_committed(self, segment: TranscriptSegment) -> CommittedSegment:
        """Bug C: convert a legacy (Deepgram/Gemini) FINAL segment into a CommittedSegment.

        Deepgram/Gemini не дают word-level данных, поэтому words=[]; текст и тайминги
        берём как есть. Нужно, чтобы _persist_segments видел сегменты legacy-движков
        (иначе finalize считает транскрипт пустым).
        """
        speaker = segment.speaker or UNKNOWN_SPEAKER
        return CommittedSegment(
            text=segment.text,
            start_time=segment.start_time,
            end_time=segment.end_time,
            wall_clock=segment.timestamp,
            speaker_id=speaker,
            speaker_label=segment.speaker or None,
            origin=SegmentOrigin.LIVE_COMMITTED,
        )

    def _on_legacy_transcript(self, segment: TranscriptSegment, is_partial: bool):
        """Legacy callback from Deepgram/Gemini services."""
        if not is_partial:
            # Apply speaker mapping
            if segment.speaker in self.speaker_mapping:
                segment.speaker = self.speaker_mapping[segment.speaker]
            elif self.current_speaker:
                segment.speaker = self.current_speaker

            self.context_analyzer.add_segment(segment)

            # Bug C: финальные legacy-сегменты должны попадать в committed-store,
            # иначе finalize/_persist_segments видят пустой транскрипт. Партиалы
            # (is_partial=True) сюда не доходят → дублей нет. Не зависит от _ws_send.
            if segment.text and segment.text.strip():
                self._committed_segments.append(self._legacy_to_committed(segment))

            # Also write to audio recorder if not ElevenLabs
            # (ElevenLabs writes in streaming_service._send_audio_loop)

        # Send to client
        if self._ws_send:
            asyncio.create_task(self._send_transcript(segment, is_partial))

            if not is_partial:
                # Update turn assembler and send turn_update
                turn, _ = self._turn_assembler.push(
                    speaker=segment.speaker,
                    text=segment.text,
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    wall_clock=segment.timestamp,
                )
                asyncio.create_task(self._send_turn_update(turn))

                # Feed meeting memory
                self._meeting_memory.ingest_turn(turn)
                if self._meeting_memory.needs_summary_update() and self.llm_client:
                    asyncio.create_task(self._meeting_memory.update_summary(self.llm_client))

                # Check auto-triggers for final segments
                asyncio.create_task(self._check_legacy_auto_triggers(segment.text))

                # Conversation Tree: обновить дерево общения (fire-and-forget)
                self._fire_committed_hook(segment)

    # ---------------------------------------------------------------
    # AI Hint System (debounced)
    # ---------------------------------------------------------------

    def _schedule_hint_check(self, segment: CommittedSegment):
        """Add segment to buffer, reset debounce timer."""
        self._hint_buffer.append(segment)
        if self._hint_debounce_task and not self._hint_debounce_task.done():
            self._hint_debounce_task.cancel()
        self._hint_debounce_task = asyncio.create_task(self._debounced_hint_check())

    def _auto_interval(self) -> float:
        """Этап 9: минимальный интервал между авто-подсказками."""
        return float(self._ai("auto_suggestion_min_interval_seconds", HINT_COOLDOWN_SEC))

    def set_speaker_audio_metadata(self, *, source_map: Optional[dict] = None,
                                   channel_map: Optional[dict] = None) -> None:
        """Этап 6/7: задать manual structured speaker↔audio link для Signal Engine.

        source_map: {speaker_label: source_id}; channel_map: {speaker_label: channel_label}.
        Holders сохраняются как явная runtime-metadata (трактуются как стабильный link)."""
        if source_map is not None:
            self.speaker_audio_source_map = dict(source_map)
        if channel_map is not None:
            self.speaker_channel_map = dict(channel_map)

    def set_audio_capture_metadata(self, payload: Any) -> bool:
        """Этап 15: сохранить безопасную audio capture route metadata (диагностика/телеметрия).

        Парсит payload в AudioCaptureMetadata (raw device label/id хэшируются, сырьё отбрасывается).
        НЕ вызывает set_speaker_audio_metadata, НЕ создаёт source attribution, НЕ трогает
        speaker_identity_hints и НЕ влияет на reconciliation. route/source_kind — техническая зона
        записи, НЕ сторона. Логирует только агрегаты (route/pipeline/каналы), без raw labels/ids.
        Возвращает True, если метаданные приняты."""
        try:
            meta = parse_audio_capture_metadata(payload)
        except Exception:  # noqa: BLE001 — телеметрия не должна ломать поток
            logger.warning("[AudioCapture] невалидный payload — проигнорирован")
            return False
        self._audio_capture_metadata = meta
        logger.info(
            "[AudioCapture] route=%s pipeline=%s source_kind=%s actual_channels=%s actual_sample_rate=%s",
            meta.route, meta.capture_pipeline, meta.source_kind,
            meta.actual_channel_count, meta.actual_sample_rate)
        return True

    def get_audio_capture_metadata(self) -> Optional[AudioCaptureMetadata]:
        """Этап 15: текущая безопасная audio capture route metadata (или None)."""
        return self._audio_capture_metadata

    def ingest_audio_frame_v2_shadow(self, data: bytes) -> bool:
        """Этап 16: принять MAUD2 v2 shadow-кадр (диагностика). Возвращает True, если принят.

        НЕ вызывает STT, НЕ создаёт source attribution, НЕ трогает speaker_identity_hints, НЕ
        кормит attribution observations. Только безопасные агрегаты. Raw audio не хранится/не логируется.
        Управляется флагами ENABLED/ACCEPT_FRAMES. Лог — изредка, только агрегаты.
        """
        settings = get_settings()
        if not getattr(settings, "ai_audio_multichannel_shadow_enabled", True):
            return False
        if not getattr(settings, "ai_audio_multichannel_shadow_accept_frames", True):
            self._multichannel_shadow_ingest.note_dropped()
            return False
        accepted = self._multichannel_shadow_ingest.ingest_frame(data)
        if accepted and self._multichannel_shadow_ingest.frame_count % self._mc_shadow_log_every == 1:
            ing = self._multichannel_shadow_ingest
            logger.info(
                "[AudioV2Shadow] accepted=true frames=%s channels=%s sample_rate=%s gaps=%s errors=%s",
                ing.frame_count, ing.last_channels, ing.last_sample_rate,
                ing.sequence_gap_count, ing.parse_error_count)
        # Этап 17: per-channel STT canary (opt-in). Stage 16 поведение выше не меняется. Ошибка
        # per-channel STT не влияет на legacy mono STT и на v2 shadow stats.
        if accepted:
            try:
                self._feed_per_channel_stt(data)
            except Exception:  # noqa: BLE001 — per-channel STT никогда не ломает поток
                logger.debug("[PerChannelStt] feed failed (ignored)", exc_info=False)
        return accepted

    def get_multichannel_shadow_stats(self):
        """Этап 16: снимок безопасных агрегатов v2 shadow ingest."""
        enabled = bool(getattr(get_settings(), "ai_audio_multichannel_shadow_enabled", True))
        return self._multichannel_shadow_ingest.get_stats(enabled=enabled)

    # --- Этап 17: per-channel STT canary ---

    def _get_per_channel_stt_runtime_config(self):
        """Resolve per-channel STT config (global + per-meeting canary override)."""
        return resolve_per_channel_stt_runtime_config(get_settings(), self.ai_settings)

    def _build_per_channel_stt_adapter(self, config):
        """Этап 18: построить provider-адаптер по config.provider. API-ключ берётся из
        session._elevenlabs_key (НЕ из ai_settings snapshot). provider=noop → no-op (без вызовов)."""
        from ..core.audio.per_channel_stt_adapter import build_per_channel_stt_adapter
        return build_per_channel_stt_adapter(config, api_key=self._elevenlabs_key)

    def _ensure_per_channel_stt_pipeline(self, config):
        """Создать/обновить pipeline + semaphore + provider-адаптер под текущий config."""
        # Адаптер: явная инъекция (тесты) имеет приоритет, иначе строим по provider.
        provider_key = (config.provider, config.model_id, config.language_code)
        if self._per_channel_stt_pipeline is None:
            adapter = self._per_channel_stt_adapter or self._build_per_channel_stt_adapter(config)
            self._per_channel_stt_pipeline = PerChannelSttPipeline(config, adapter)
            self._per_channel_stt_provider_key = provider_key
        else:
            self._per_channel_stt_pipeline.update_config(config)
            # Пересобрать адаптер, если provider/model/language изменились (и нет явной инъекции).
            if self._per_channel_stt_adapter is None and provider_key != self._per_channel_stt_provider_key:
                self._per_channel_stt_pipeline.set_adapter(self._build_per_channel_stt_adapter(config))
                self._per_channel_stt_provider_key = provider_key
        if self._per_channel_stt_sem_size != config.max_concurrent_transcribes:
            self._per_channel_stt_semaphore = asyncio.Semaphore(config.max_concurrent_transcribes)
            self._per_channel_stt_sem_size = config.max_concurrent_transcribes
        return self._per_channel_stt_pipeline

    def _feed_per_channel_stt(self, data: bytes) -> None:
        """Если per-channel STT canary включён — сегментировать v2 кадр и запланировать транскрипцию.

        НЕ заменяет legacy STT. НЕ выводит сторону. channel_{index} — техническая зона записи.
        """
        config = self._get_per_channel_stt_runtime_config()
        if not config.enabled:
            return
        try:
            parsed = parse_audio_frame_v2(data)
        except Exception:  # noqa: BLE001 — битый кадр уже учтён Stage 16 ingest
            return
        pipeline = self._ensure_per_channel_stt_pipeline(config)
        segments = pipeline.ingest_frame(parsed)
        for seg in segments:
            self._schedule_per_channel_transcribe(seg, config)

    def _schedule_per_channel_transcribe(self, segment, config) -> None:
        """Запланировать async-транскрипцию сегмента (не блокирует WS-аудио). Без loop — пропуск."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._per_channel_stt_transcribe_task(segment, config))
        self._per_channel_stt_tasks.add(task)
        task.add_done_callback(self._per_channel_stt_tasks.discard)

    async def _per_channel_stt_transcribe_task(self, segment, config) -> None:
        """Транскрибировать сегмент; в shadow — подавить кандидата, иначе отдать в reconciler.

        Полностью защищена: ЛЮБАЯ ошибка (в т.ч. при teardown сессии) проглатывается и не ломает
        legacy/v2 поток и не валит event loop. channel_{index} — техническая зона; сторона НЕ выводится.
        """
        try:
            pipeline = self._per_channel_stt_pipeline
            if pipeline is None:
                return
            sem = self._per_channel_stt_semaphore
            if sem is not None:
                async with sem:
                    candidate = await pipeline.transcribe_segment(segment)
            else:
                candidate = await pipeline.transcribe_segment(segment)
            if candidate is None:
                return
            if config.shadow_mode:
                pipeline.mark_candidate_suppressed()
                return
            # active: source candidate → SourceAttributionReconciler (он сам решит shadow/attach).
            # observe не создаёт attribution напрямую и не трогает speaker_identity_hints.
            payload = pipeline.segment_to_source_candidate_payload(candidate)
            self.observe_source_attribution_candidate(payload)
            pipeline.mark_candidate_emitted()
        except Exception:  # noqa: BLE001 — per-channel STT никогда не ломает поток/loop
            logger.debug("[PerChannelStt] transcribe task failed (ignored)", exc_info=False)

    def get_per_channel_stt_stats(self):
        """Этап 17: снимок безопасных агрегатов per-channel STT (или None)."""
        if self._per_channel_stt_pipeline is None:
            return None
        return self._per_channel_stt_pipeline.get_stats()

    async def drain_per_channel_stt_tasks(self) -> None:
        """Дождаться завершения запланированных per-channel STT задач (finalization/тесты)."""
        if self._per_channel_stt_tasks:
            await asyncio.gather(*list(self._per_channel_stt_tasks), return_exceptions=True)

    def observe_speaker_audio_attribution(self, payload: Any) -> int:
        """Этап 7: принять structured observations (speaker_label ↔ source/channel) из live-потока.

        Извлекает observations (не парсит transcript text), кормит tracker. Возвращает число
        принятых наблюдений. payload и raw labels/source ids НЕ логируются."""
        try:
            observations = extract_speaker_audio_observations_from_payload(payload)
        except Exception:  # noqa: BLE001 — attribution не должна ломать поток
            return 0
        if not observations:
            return 0
        return self._speaker_audio_attribution.observe_many(observations)

    def bridge_segment_source_attribution(
        self, segment, *, audio_source_id: Optional[str] = None, channel_label: Optional[str] = None,
        device_role: Optional[str] = None, route: Optional[str] = None,
        attribution_confidence: Optional[float] = None, source_is_isolated: bool = False,
        attribution_source: str = "unknown", source_kind: str = "unknown",
        turn_index: Optional[int] = None,
    ) -> bool:
        """Этап 9 bridge: будущий isolated STT/diarization-путь зовёт это, чтобы безопасно
        проставить source_attribution на committed segment. speaker_label/segment_id берутся
        с самого сегмента. Возвращает True, если attribution безопасна (should_emit) и проставлена;
        False для общего room-mic/без isolation. Сторона не выводится. Значения не логируются."""
        if isinstance(segment, dict):
            label, seg_id = segment.get("speaker_label"), segment.get("segment_id")
        else:
            label, seg_id = getattr(segment, "speaker_label", None), getattr(segment, "segment_id", None)
        attribution = build_segment_source_attribution_dict(
            speaker_label=label, audio_source_id=audio_source_id, channel_label=channel_label,
            device_role=device_role, route=route, attribution_confidence=attribution_confidence,
            source_is_isolated=source_is_isolated, attribution_source=attribution_source,
            source_kind=source_kind, turn_index=turn_index,
            segment_id=(str(seg_id) if seg_id else None))
        if attribution is None:
            return False
        attach_source_attribution_to_committed_segment(segment, attribution)
        return True

    def _get_source_reconcile_runtime_config(self):
        """Этап 11: resolve runtime config (global + per-meeting canary override)."""
        return resolve_source_reconcile_runtime_config(get_settings(), self.ai_settings)

    def observe_source_attribution_candidate(self, payload: Any) -> int:
        """Этап 10/11: принять isolated/per-channel source candidate (source/channel ± text/time,
        без speaker_label). enabled=false → 0 (старое поведение). Применяет runtime-пороги. raw
        payload/text/source ids НЕ логируются. Список → каждый элемент."""
        config = self._get_source_reconcile_runtime_config()
        if not config.enabled:
            return 0
        self._source_attribution_reconciler.apply_runtime_config(config)
        try:
            if isinstance(payload, (list, tuple)):
                return self._source_attribution_reconciler.observe_candidates(payload)
            cand = extract_source_candidate_from_payload(payload)
        except Exception:  # noqa: BLE001 — reconciliation не должна ломать поток
            return 0
        if cand is None:
            return 0
        return 1 if self._source_attribution_reconciler.observe_candidate(cand) else 0

    def reconcile_source_attribution_for_segment(self, segment: Any) -> bool:
        """Этап 10/11: сопоставить committed segment (speaker_label) с накопленным isolated source
        candidate. Прикрепляет source_attribution ТОЛЬКО при decision.actual_attach (shadow_mode=
        false). В shadow считает would_attach и пишет SOURCE_RECONCILE_TRACE, но НЕ прикрепляет.

        Не перезаписывает уже заданный source_attribution (bridge/manual). Возвращает True если
        реально прикрепили. Логи/trace — ТОЛЬКО агрегаты/категории, без raw text/labels/source ids.
        Примечание: bridge_segment_source_attribution — это явный internal вызов и НЕ подчиняется
        shadow reconcile (он намеренно ставит attribution напрямую)."""
        config = self._get_source_reconcile_runtime_config()
        self._reconcile_last_shadow = config.shadow_mode
        if not config.enabled:
            return False
        self._source_attribution_reconciler.apply_runtime_config(config)
        check_id = uuid.uuid4().hex[:12]
        t0 = time.monotonic()
        match = self._source_attribution_reconciler.reconcile_segment(segment)
        latency_ms = int((time.monotonic() - t0) * 1000)
        decision = evaluate_source_reconcile_decision(match, config)

        if decision.would_attach_without_shadow:
            self._reconcile_would_attach += 1
        if decision.actual_attach:
            self._reconcile_actual_attach += 1
        self._reconcile_decision_reasons[decision.reason] = \
            self._reconcile_decision_reasons.get(decision.reason, 0) + 1

        if config.trace_enabled and (
            config.trace_sample_rate >= 1.0 or random.random() < config.trace_sample_rate
        ):
            ev = build_source_reconcile_trace_event(
                check_id=check_id, config=config, match=match, decision=decision,
                reconciler_stats=self._source_attribution_reconciler.get_stats(),
                session_id=self.user_id, meeting_id=self.db_session_id, latency_ms=latency_ms)
            log_source_reconcile_trace(logger, ev)

        if decision.actual_attach and match.attribution_dict:
            attach_source_attribution_to_committed_segment(segment, match.attribution_dict)
            return True
        return False

    def _collect_speaker_audio_metadata(self, ctx: Optional[dict] = None):
        """Собрать итоговый SpeakerAudioLinkMap из structured-источников (или None).

        Объединяет: manual holders (set_speaker_audio_metadata), tracker.build_link_map()
        (устойчивая live-attribution) и structured-контейнеры из ctx, если есть. Не парсит
        transcript text. Если ничего нет — None."""
        links = []
        if self.speaker_audio_source_map or self.speaker_channel_map:
            mlm = extract_audio_links_from_metadata(
                audio_source_metadata=(self.speaker_audio_source_map or None),
                channel_metadata=(self.speaker_channel_map or None))
            links.extend(mlm.links_by_stable_id.values())
        tlm = self._speaker_audio_attribution.build_link_map()
        links.extend(tlm.links_by_stable_id.values())
        if isinstance(ctx, dict):
            container = {k: ctx[k] for k in (
                "speaker_sources", "source_by_speaker", "speaker_channels",
                "channel_by_speaker", "speaker_audio_links") if ctx.get(k)}
            if container:
                links.extend(
                    extract_audio_links_from_metadata(
                        audio_source_metadata=container).links_by_stable_id.values())
        if not links:
            return None
        return build_speaker_audio_link_map(links)

    async def _signal_flow(self, text: str, recent: str, doc_context: str,
                           source_method: str = "", ctx: Optional[dict] = None) -> bool:
        """Signal Engine (Этап 2). Возвращает True, если signal-слой обработал ситуацию
        (вызывающий делает return); False — продолжить legacy event/keyword flow.

        Инварианты:
        - enabled=false → полностью старый flow (LLM не зовём).
        - shadow_mode=true → только наблюдаем; старый flow продолжает работать.
        - technical error + allow_legacy_fallback → старый flow может сработать.
        - invalid/validation/should_prompt=false/weak в live → осознанное молчание (НЕ legacy).
        """
        config = resolve_signal_runtime_config(get_settings(), self.ai_settings)
        if not config.enabled:
            return False  # полностью старый flow

        # Speaker Identity Graph v1: подтверждённые роли = manual_correction, остальное —
        # метки из диалога (unknown). Без угадывания. Пустой граф → speaker_context="".
        # Hidden per-meeting hints (Этап 5) из snapshot AI-настроек (dict или объект).
        ai = self.ai_settings
        identity_hints = (ai.get("speaker_identity_hints") if isinstance(ai, dict)
                          else getattr(ai, "speaker_identity_hints", None))
        # Этап 8/10: structured source candidates + per-segment attribution из ctx.
        # transcript text не парсится как метаданные. Основной поток — observe/reconcile из
        # MeetingRoom committed-hook; здесь — если ctx несёт structured candidates/segment.
        if isinstance(ctx, dict):
            for cand_key in ("source_candidates", "source_attribution_candidates",
                             "multi_channel_candidates"):
                cands = ctx.get(cand_key)
                if cands:
                    self.observe_source_attribution_candidate(cands)
            for seg_key in ("current_segment", "committed_segment", "last_segment", "segment"):
                seg = ctx.get(seg_key)
                if seg is not None:
                    self.reconcile_source_attribution_for_segment(seg)  # source_attribution до observe
                    payload = build_observation_payload_from_segment(seg)
                    if payload:
                        self.observe_speaker_audio_attribution(payload)
        audio_link_map = self._collect_speaker_audio_metadata(ctx)
        speaker_map = self._speaker_identity_service.build_runtime_map(
            manual_overrides=(self.speaker_roles or None),
            recent_dialog=recent,
            identity_hints=identity_hints,
            audio_link_map=audio_link_map,
        )
        speaker_context = (self._speaker_identity_service.build_context_text(speaker_map)
                           if speaker_map.speakers else "")

        check_id = uuid.uuid4().hex[:12]
        t0 = time.monotonic()
        result = await self._signal_engine.classify(
            llm_client=self.llm_client,
            role_name=self._role_name(),
            recent_dialog=recent,
            current_text=text,
            document_context=doc_context,
            speaker_context=speaker_context,
            timeout_seconds=config.llm_timeout_seconds,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        sig = result.signal
        decision = evaluate_signal_decision(sig, result, config)

        # Безопасный structured trace (без текста переговоров/имён при include_text=false)
        if config.trace_enabled and (
            config.trace_sample_rate >= 1.0 or random.random() < config.trace_sample_rate
        ):
            event = build_signal_trace_event(
                check_id=check_id, result=result, decision=decision,
                shadow_mode=config.shadow_mode,
                recent_dialog=recent, current_text=text, document_context=doc_context,
                session_id=self.user_id, meeting_id=self.db_session_id,
                source_method=source_method or None, latency_ms=latency_ms,
                include_text=config.trace_include_text,
                speaker_context=speaker_context, speaker_map=speaker_map,
                audio_link_map=audio_link_map,
                attribution_stats=self._speaker_audio_attribution.get_stats(),
                source_reconcile_stats=self._source_attribution_reconciler.get_stats(),
                source_reconcile_decision_stats={
                    "shadow_mode": self._reconcile_last_shadow,
                    "would_attach_count": self._reconcile_would_attach,
                    "actual_attach_count": self._reconcile_actual_attach,
                    "decision_reasons": dict(self._reconcile_decision_reasons),
                },
                audio_capture_metadata=self._audio_capture_metadata,
                multichannel_shadow_stats=(
                    self.get_multichannel_shadow_stats()
                    if get_settings().ai_audio_multichannel_shadow_trace_enabled else None),
                per_channel_stt_stats=self.get_per_channel_stt_stats(),
            )
            log_signal_trace(logger, event)

        # Этап 17: отдельный PER_CHANNEL_STT_TRACE (только агрегаты), если canary включён.
        pcfg = self._get_per_channel_stt_runtime_config()
        if (pcfg.enabled and pcfg.trace_enabled and self._per_channel_stt_pipeline is not None
                and (pcfg.trace_sample_rate >= 1.0 or random.random() < pcfg.trace_sample_rate)):
            pcs_event = build_per_channel_stt_trace_event(
                check_id=check_id, stats=self.get_per_channel_stt_stats(), config=pcfg,
                session_id=self.user_id, meeting_id=self.db_session_id)
            log_per_channel_stt_trace(logger, pcs_event)

        # --- маппинг decision → поведение flow ---
        if decision.legacy_fallback_allowed:
            return False  # тех.сбой + allow_legacy → старый flow может сработать
        if config.shadow_mode:
            return False  # наблюдаем; старый flow работает как сейчас
        if not decision.actual_should_prompt:
            return True   # молчание (invalid/should_prompt_false/weak) — НЕ legacy

        # live + actual_should_prompt=true
        now = time.time()
        key = decision.cooldown_key or f"signal:{sig.novelty_key}"
        if now - self._auto_trigger_cooldown.get(key, 0) < self._auto_interval():
            return True  # cooldown → молчание
        self._auto_trigger_cooldown[key] = now

        status = ("Обнаружен переговорный риск…" if sig.risk_level == "high"
                  else "Анализирую переговорную ситуацию…")
        await self._send_analysis_status(status)
        await self._auto_suggestion_from_signal(sig, recent, doc_context, speaker_context=speaker_context)
        await self._send_analysis_status(None)
        return True

    async def _debounced_hint_check(self):
        """Wait for pause, then check buffered segments for events/keywords."""
        await asyncio.sleep(HINT_DEBOUNCE_SEC)

        if not self._hint_buffer or not self.llm_client:
            return
        # Этап 9: авто-подсказки можно отключить (manual продолжает работать)
        if not self._ai("auto_suggestions_enabled", True):
            self._hint_buffer.clear()
            return
        if len(self._committed_segments) < MIN_SEGMENTS_FOR_HINT:
            return

        # Aggregate buffer text
        batch_text = " ".join(s.text for s in self._hint_buffer)
        self._hint_buffer.clear()

        now = time.time()
        ctx = self._ctx_builder.build_reactive(batch_text)
        recent = ctx["recent_dialog"]
        doc_context = await self._augment_doc_context(ctx["document_context"], batch_text)

        # --- Signal Engine (Этап 2): contextual classification ---
        if await self._signal_flow(batch_text, recent, doc_context,
                                   source_method="debounced_hint_check", ctx=ctx):
            return

        # --- Event detection (priority over keywords) ---
        events = self._event_detector.detect(batch_text)
        for ev in events:
            cooldown_key = f"event:{ev.event_type}"
            last = self._auto_trigger_cooldown.get(cooldown_key, 0)
            if now - last < self._auto_interval():
                continue
            self._auto_trigger_cooldown[cooldown_key] = now

            await self._send_analysis_status(ev.status_message)
            await self._auto_suggestion(ev.keyword_for_prompt, recent, doc_context)
            await self._send_analysis_status(None)
            return  # event handled, skip keyword fallback

        # --- Keyword fallback ---
        keywords = self.context_analyzer.detect_trigger_keywords(batch_text)

        triggered_keyword = None
        for kw in keywords:
            last_trigger = self._auto_trigger_cooldown.get(kw, 0)
            if now - last_trigger >= self._auto_interval():
                triggered_keyword = kw
                self._auto_trigger_cooldown[kw] = now
                break

        if not triggered_keyword:
            return

        status_msg = self._keyword_status.get(
            triggered_keyword, f"Анализирую: «{triggered_keyword}»..."
        )
        await self._send_analysis_status(status_msg)
        await self._auto_suggestion(triggered_keyword, recent, doc_context)
        await self._send_analysis_status(None)

    async def _check_legacy_auto_triggers(self, text: str):
        """Legacy auto-trigger check for Deepgram/Gemini (event-first, keyword fallback)."""
        if not self.llm_client:
            return
        # Этап 9: авто-подсказки можно отключить (manual продолжает работать)
        if not self._ai("auto_suggestions_enabled", True):
            return

        now = time.time()
        ctx = self._ctx_builder.build_reactive(text)
        recent = ctx["recent_dialog"]
        doc_context = await self._augment_doc_context(ctx["document_context"], text)

        # --- Signal Engine (Этап 2): contextual classification ---
        if await self._signal_flow(text, recent, doc_context,
                                   source_method="check_legacy_auto_triggers", ctx=ctx):
            return

        # --- Event detection (priority) ---
        events = self._event_detector.detect(text)
        for ev in events:
            cooldown_key = f"event:{ev.event_type}"
            last = self._auto_trigger_cooldown.get(cooldown_key, 0)
            if now - last < self._auto_interval():
                continue
            self._auto_trigger_cooldown[cooldown_key] = now

            await self._send_analysis_status(ev.status_message)
            await self._auto_suggestion(ev.keyword_for_prompt, recent, doc_context)
            await self._send_analysis_status(None)
            return  # event handled

        # --- Keyword fallback ---
        keywords = self.context_analyzer.detect_trigger_keywords(text)

        for keyword in keywords:
            last_trigger = self._auto_trigger_cooldown.get(keyword, 0)
            if now - last_trigger < self._auto_interval():
                continue

            self._auto_trigger_cooldown[keyword] = now

            status_msg = self._keyword_status.get(
                keyword, f"Анализирую: «{keyword}»..."
            )
            await self._send_analysis_status(status_msg)
            await self._auto_suggestion(keyword, recent, doc_context)
            await self._send_analysis_status(None)
            break

    # ---------------------------------------------------------------
    # Manual suggestion / strengthen
    # ---------------------------------------------------------------

    async def request_manual_suggestion(self):
        """Handle manual suggestion request — generates tactical hint cards."""
        if not self.llm_client:
            await self._send_error("LLM not configured")
            return

        await self._send_json({"type": "suggestion_loading", "loading": True})
        await self._send_analysis_status("Формирую AI Подсказки...")

        ctx = self._ctx_builder.build_tactical(
            topic=self.document_loader.meeting_topic,
            notes=self.document_loader.meeting_notes,
            negotiation_type=self.negotiation_type,
            meeting_role=self.meeting_role,
            opponent_weaknesses=self.opponent_weaknesses,
        )
        context = ctx.pop("recent_dialog", "")
        if not context:
            await self._send_error("Нет данных для анализа")
            await self._send_analysis_status(None)
            await self._send_json({"type": "suggestion_loading", "loading": False})
            return

        settings = get_settings()
        if self._ai("suggestion_structured_enabled", settings.suggestion_structured_enabled):
            # Этап 6: единая сборка контекста через ContextPack
            pack = await self._build_context_pack_for_prompt(
                mode="manual", query_text=context,
                meeting_context_block=self._meeting_context_block(ctx),
                recent_dialog=context, document_context=ctx.get("document_context", ""),
            )
            doc_combined = pack.combined_documents_text()
            max_cards = self._ai("max_manual_cards", settings.suggestion_max_cards_manual)
            prompt = build_manual_cards_prompt(
                self._role_name(), pack.text_for("meeting_context"),
                pack.text_for("recent_dialog"), doc_combined,
                max_cards, knowledge_context=pack.text_for("knowledge"),
                previous_meetings_context=pack.text_for("previous_meeting"),
                letters_context=pack.text_for("letters"))
            raw = await self.llm_client.get_suggestion_async(prompt, max_tokens=_mode_tokens(self._mode(), "manual"))
            await self._emit_suggestion_cards(raw, "manual", doc_context_text=doc_combined)
        else:
            # Этап 4: добавить релевантные фрагменты документов встречи (из БД)
            ctx["document_context"] = await self._augment_doc_context(ctx.get("document_context", ""), context)
            prompt = self.prompt_builder.build_tactical_hints_prompt(recent_dialog=context, **ctx)
            raw = await self.llm_client.get_suggestion_async(prompt, max_tokens=600)
            if raw:
                for hint in self._parse_hints_array(raw):
                    await self._send_structured_suggestion(hint, is_auto=False)

        await self._send_analysis_status(None)
        await self._send_json({"type": "suggestion_loading", "loading": False})

    async def strengthen_position(self):
        """Handle strengthen position request (streaming kept for long responses)."""
        if not self.llm_client:
            await self._send_error("LLM not configured")
            return

        await self._send_json({"type": "strengthen_loading", "loading": True})
        await self._send_analysis_status("Анализирую позицию и аргументы...")

        ctx = self._ctx_builder.build_strategic(
            topic=self.document_loader.meeting_topic,
            notes=self.document_loader.meeting_notes,
            negotiation_type=self.negotiation_type,
            meeting_role=self.meeting_role,
            opponent_weaknesses=self.opponent_weaknesses,
        )
        context = ctx.pop("full_transcript", "")
        if not context:
            await self._send_error("Нет данных для анализа")
            await self._send_analysis_status(None)
            await self._send_json({"type": "strengthen_loading", "loading": False})
            return

        # Этап 6: единая сборка контекста через ContextPack (strengthen → полный транскрипт)
        pack = await self._build_context_pack_for_prompt(
            mode="strengthen", query_text=context,
            meeting_context_block=self._meeting_context_block(ctx),
            full_transcript=context, document_context=ctx.get("document_context", ""),
        )
        prompt = build_strengthen_prompt(
            self._role_name(), pack.text_for("meeting_context"),
            pack.text_for("full_transcript"), pack.combined_documents_text(),
            knowledge_context=pack.text_for("knowledge"),
            previous_meetings_context=pack.text_for("previous_meeting"),
            letters_context=pack.text_for("letters"),
        )

        logger.info(f"[Strengthen] docs={len(self.document_loader.documents)}, "
                     f"topic='{self.document_loader.meeting_topic}', "
                     f"type='{self.negotiation_type}', prompt_len={len(prompt)}")
        logger.debug(f"[Strengthen] PROMPT:\n{prompt}")

        # Этап 9: отдельная модель для усиления + max_tokens по режиму
        strengthen_client = self._client_for_model(self._ai("strengthen_model", None))
        full_text_parts: list[str] = []
        async for chunk_text in strengthen_client.get_suggestion_streaming_async(
            prompt, max_tokens=_mode_tokens(self._mode(), "strengthen")
        ):
            full_text_parts.append(chunk_text)
            await self._send_json({"type": "suggestion_chunk", "text": chunk_text})

        # Persist strengthen result
        if full_text_parts:
            combined = "".join(full_text_parts)
            asyncio.create_task(self._persist_suggestion(
                {"text": combined, "type": "priority"},
                is_auto=False,
                source="strengthen",
            ))

        await self._send_analysis_status(None)
        await self._send_json({"type": "strengthen_loading", "loading": False})

    # ---------------------------------------------------------------
    # Batch finalization
    # ---------------------------------------------------------------

    async def request_batch_finalize(self):
        """Run post-meeting batch transcription with diarization."""
        if not self.audio_recorder or not self.audio_recorder.file_path:
            await self._send_error("Нет записи аудио для финализации")
            return

        if not self._elevenlabs_key:
            await self._send_error("API ключ ElevenLabs не настроен")
            return

        wav_bytes = self.audio_recorder.to_wav_bytes()
        if not wav_bytes:
            await self._send_error("Аудио файл пуст")
            return

        await self._send_status("Финализация транскрипции (batch)...")

        try:
            from ..core.transcription.batch_service import BatchTranscriptionService
            batch = BatchTranscriptionService(api_key=self._elevenlabs_key)
            segments = await batch.transcribe(wav_bytes)

            # Replace committed segments with batch results
            self._committed_segments = segments

            # Rebuild turns from batch segments
            items = [
                (
                    s.speaker_label or s.speaker_id,
                    s.text,
                    s.start_time,
                    s.end_time,
                    s.wall_clock,
                )
                for s in segments
            ]
            rebuilt_turns = self._turn_assembler.rebuild(items)

            # Send to client
            await self._send_json({"type": "turns_reset"})
            await self._send_json({
                "type": "batch_finalized",
                "segments": [s.to_wire_full() for s in segments],
            })
            for turn in rebuilt_turns:
                await self._send_turn_update(turn)
            await self._send_status(
                f"Финализация завершена: {len(segments)} сегментов"
            )
        except Exception as e:
            logger.error(f"[BatchFinalize] Error: {e}")
            await self._send_error(f"Ошибка финализации: {e}")

    # ---------------------------------------------------------------
    # Speaker / context
    # ---------------------------------------------------------------

    def mark_speaker(self, speaker_name: str):
        """Mark current speaker for identification."""
        self.current_speaker = speaker_name

    def set_speaker_role(self, speaker_name: str, side: str):
        """Assign public negotiation side (self|opponent) to a speaker label.

        Принимает алиасы (we/not_us/ally/third_party/…); в live-map хранятся ТОЛЬКО
        нормализованные self/opponent. None/unknown/'' → удалить спикера из map.
        """
        from .speaker_roles import normalize_side  # локальный импорт: избегаем цикла
        norm = normalize_side(side)
        if norm:
            self.speaker_roles[speaker_name] = norm
        else:
            self.speaker_roles.pop(speaker_name, None)

    def set_speaker_name(self, speaker_label: str, display_name: str | None):
        """Назначить человекочитаемое имя метке спикера (SM_0 → «Иван»). Пусто → снять."""
        name = (display_name or "").strip()
        if name:
            self.speaker_names[speaker_label] = name
        else:
            self.speaker_names.pop(speaker_label, None)

    def set_speaker_names(self, names: Dict[str, str]) -> None:
        """Заменить in-memory кэш имён спикеров ({speaker_label: display_name})."""
        self.speaker_names = {k: v for k, v in (names or {}).items() if v}

    def update_meeting_context(self, topic: str, notes: str):
        """Update meeting topic and notes."""
        self.document_loader.meeting_topic = topic
        self.document_loader.meeting_notes = notes

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    def _get_committed_context(self, minutes: int = 5) -> str:
        """Format recent committed segments as text for LLM prompts.

        Uses confidence gating: low-confidence segments are marked.
        """
        if not self._committed_segments:
            return ""

        from datetime import timedelta
        cutoff = datetime.now() - timedelta(minutes=minutes)
        recent = [
            s for s in self._committed_segments
            if s.wall_clock >= cutoff
        ]

        lines = []
        for seg in recent:
            ts = seg.wall_clock.strftime("%H:%M:%S")
            # Этап 8: сторона/спикер реплики с учётом segment-level коррекций
            speaker, side = self._resolve_segment(seg)
            role_tag = ROLE_LABELS.get(side or "", "")
            label = f"{speaker} [{role_tag}]" if role_tag else speaker
            line = f"[{ts}] {label}: {seg.text}"
            if seg.is_low_confidence:
                line += "  [НИЗКАЯ УВЕРЕННОСТЬ]"
            lines.append(line)

        return "\n".join(lines)

    @property
    def committed_segments(self) -> List[CommittedSegment]:
        """Public access to committed segments (read-only intent)."""
        return self._committed_segments

    @property
    def turns(self):
        """Public access to assembled turns."""
        return self._turn_assembler.turns

    def recent_dialog_with_sides(self, max_turns: int = 40, max_chars: int = 6000) -> str:
        """Связный диалог для LLM-экстрактора дерева общения.

        Хвост из последних turns (TurnAssembler уже склеил пословные коммиты в реплики),
        каждая строка: «[МЫ|НЕ МЫ] speaker: text». Сторона — из speaker_roles (канонизация
        legacy через ROLE_LABELS). Спикеры без стороны идут без тега. Обрезка по хвосту до
        max_chars (самое свежее важнее)."""
        turns = self._turn_assembler.turns
        if not turns:
            return ""
        lines: list[str] = []
        for t in turns[-max_turns:]:
            text = (t.text or "").strip()
            if not text:
                continue
            role_tag = ROLE_LABELS.get(self.speaker_roles.get(t.speaker, ""), "")
            prefix = f"[{role_tag}] " if role_tag else ""
            lines.append(f"{prefix}{t.speaker}: {text}")
        dialog = "\n".join(lines)
        if len(dialog) > max_chars:
            dialog = dialog[-max_chars:]
            nl = dialog.find("\n")
            if nl != -1:
                dialog = dialog[nl + 1:]
        return dialog

    def _get_turn_context(self, minutes: int = 5) -> str:
        """Format recent turns as text (prepared for future LLM prompts)."""
        if not self._turn_assembler.turns:
            return ""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(minutes=minutes)
        lines = []
        for t in self._turn_assembler.turns:
            if t.wall_clock >= cutoff:
                ts = t.wall_clock.strftime("%H:%M:%S")
                role_tag = ROLE_LABELS.get(self.speaker_roles.get(t.speaker, ""), "")
                label = f"{t.speaker} [{role_tag}]" if role_tag else t.speaker
                lines.append(f"[{ts}] {label}: {t.text}")
        return "\n".join(lines)

    # ---------------------------------------------------------------
    # WebSocket message helpers
    # ---------------------------------------------------------------

    async def _send_json(self, data: dict):
        if self._ws_send:
            await self._ws_send(data)

    async def _send_turn_update(self, turn):
        """Send turn_update WS message."""
        await self._send_json({"type": "turn_update", **turn.to_wire()})

    async def _send_transcript(self, segment: TranscriptSegment, is_partial: bool):
        """Legacy transcript format for Deepgram/Gemini."""
        await self._send_json({
            "type": "transcript",
            "speaker": segment.speaker,
            "text": segment.text,
            "timestamp": segment.timestamp.strftime("%H:%M:%S"),
            "is_partial": is_partial,
        })

    async def _send_suggestion(self, text: str, is_auto: bool):
        await self._send_json({
            "type": "suggestion",
            "text": text,
            "is_auto": is_auto,
        })

    async def _send_analysis_status(self, status: Optional[str]):
        await self._send_json({
            "type": "analysis_status",
            "status": status,
        })

    async def _send_structured_suggestion(self, hint: Dict[str, Any],
                                           is_auto: bool):
        """Send a structured suggestion with type, trigger, confidence, etc."""
        msg: Dict[str, Any] = {
            "type": "suggestion",
            "text": hint.get("text", ""),
            "is_auto": is_auto,
        }
        stype = hint.get("type", "")
        if stype in self._valid_suggestion_types:
            msg["suggestion_type"] = stype
        if hint.get("trigger"):
            msg["trigger"] = hint["trigger"]
        if hint.get("confidence") is not None:
            try:
                msg["confidence"] = int(hint["confidence"])
            except (ValueError, TypeError):
                pass
        if hint.get("context_info"):
            msg["context_info"] = hint["context_info"]
        await self._send_json(msg)
        # Persist to DB (fire-and-forget)
        asyncio.create_task(self._persist_suggestion(hint, is_auto))

    # ---------------------------------------------------------------
    # Этап 6: структурированные карточки подсказок
    # ---------------------------------------------------------------

    def _role_name(self) -> str:
        return (self.role_data or {}).get("name") or "переговорщик"

    def _meeting_context_block(self, ctx: dict) -> str:
        lines = []
        if ctx.get("topic"):
            lines.append(f"Тема: {ctx['topic']}")
        if ctx.get("notes"):
            lines.append(f"Цели/условия: {ctx['notes']}")
        if ctx.get("negotiation_type"):
            lines.append(f"Тип переговоров: {ctx['negotiation_type']}")
        if ctx.get("meeting_role"):
            lines.append(f"Наша роль: {ctx['meeting_role']}")
        if ctx.get("opponent_weaknesses"):
            lines.append(f"Слабые стороны оппонента: {ctx['opponent_weaknesses']}")
        return "\n".join(lines)

    async def _auto_suggestion(self, keyword: str, recent: str, doc_context: str):
        """Авто-подсказка карточками (legacy single-hint при выключенном structured)."""
        settings = get_settings()
        structured = self._ai("suggestion_structured_enabled", settings.suggestion_structured_enabled)
        if not structured:
            prompt = self.prompt_builder.build_auto_suggestion_structured_prompt(
                keyword=keyword, recent_dialog=recent, document_context=doc_context)
            raw = await self.llm_client.get_suggestion_async(prompt, max_tokens=200)
            if raw:
                hint = self._parse_single_hint(raw, keyword)
                await self._send_structured_suggestion(hint, is_auto=True)
            return
        # Этап 6: единая сборка контекста через ContextPack (doc уже augment-нут вызывающим)
        pack = await self._build_context_pack_for_prompt(
            mode="auto", query_text=(recent or keyword), meeting_context_block="",
            recent_dialog=recent, document_context=doc_context,
            document_already_augmented=True,
        )
        doc_combined = pack.combined_documents_text()
        max_cards = self._ai("max_auto_cards", settings.suggestion_max_cards_auto)
        prompt = build_auto_cards_prompt(
            self._role_name(), keyword, pack.text_for("recent_dialog"), doc_combined,
            max_cards, knowledge_context=pack.text_for("knowledge"),
            previous_meetings_context=pack.text_for("previous_meeting"),
            letters_context=pack.text_for("letters"))
        raw = await self.llm_client.get_suggestion_async(prompt, max_tokens=_mode_tokens(self._mode(), "auto"))
        await self._emit_suggestion_cards(raw, "auto", trigger=keyword, doc_context_text=doc_combined)

    async def _auto_suggestion_from_signal(self, signal, recent: str, doc_context: str,
                                           speaker_context: str = ""):
        """Авто-подсказка карточками от контекстного переговорного сигнала (Этап 1/4).

        Аналог structured-ветки _auto_suggestion, но без keyword: контекст и промпт
        строятся от NegotiationSignal + speaker_context (роли/стороны участников)."""
        settings = get_settings()
        extra = signal.intent or signal.reasoning_summary or signal.situation_type
        query_text = (f"{recent}\n{extra}".strip()) if extra else (recent or "")
        pack = await self._build_context_pack_for_prompt(
            mode="auto", query_text=query_text, meeting_context_block="",
            recent_dialog=recent, document_context=doc_context,
            document_already_augmented=True,
        )
        doc_combined = pack.combined_documents_text()
        max_cards = self._ai("max_auto_cards", settings.suggestion_max_cards_auto)
        prompt = build_auto_cards_prompt_from_signal(
            self._role_name(), signal, pack.text_for("recent_dialog"), doc_combined,
            max_cards, knowledge_context=pack.text_for("knowledge"),
            previous_meetings_context=pack.text_for("previous_meeting"),
            letters_context=pack.text_for("letters"), speaker_context=speaker_context)
        raw = await self.llm_client.get_suggestion_async(prompt, max_tokens=_mode_tokens(self._mode(), "auto"))
        await self._emit_suggestion_cards(
            raw, "auto", trigger=f"signal:{signal.situation_type}", doc_context_text=doc_combined)

    async def _emit_suggestion_cards(self, raw, source_mode: str, trigger=None, doc_context_text=""):
        settings = get_settings()
        model = getattr(self.llm_client, "model", None) if self.llm_client else None
        response = parse_suggestion_response(raw, source_mode=source_mode, model=model)
        if response is None and settings.suggestion_repair_enabled and self.llm_client:
            repair = (
                "Преобразуй ответ в ОДИН валидный JSON-объект {\"cards\":[...]} по схеме карточек. "
                "Верни ТОЛЬКО JSON, без markdown:\n\n" + (raw or "")[:8000]
            )
            repaired = await self.llm_client.get_suggestion_async(repair, max_tokens=600)
            response = parse_suggestion_response(repaired, source_mode=source_mode, model=model)
        if response is None:
            response = fallback_response("Модель вернула некорректную структуру", raw_text=raw)

        response.cards = apply_safety_checks(response.cards, doc_context_text)
        for c in response.cards:
            if trigger and not c.trigger:
                c.trigger = trigger
        if not response.cards:
            return  # 0 полезных карточек (auto без действия)

        await self._send_cards_event(response, source_mode)
        for c in response.cards:
            await self._persist_card(c, source_mode)

    async def _send_cards_event(self, response, source_mode: str):
        settings = get_settings()
        first = response.cards[0]
        msg: Dict[str, Any] = {
            "type": "suggestion",
            "is_auto": source_mode == "auto",
            # backward-compat для старого фронта
            "text": first.text,
            "suggestion_type": first.type,
            "confidence": int(round(first.confidence * 100)),
        }
        if settings.suggestion_structured_enabled:
            msg["cards"] = [c.model_dump(mode="json") for c in response.cards]
            msg["degraded"] = response.degraded
            msg["source_mode"] = source_mode
            msg["raw_text"] = None
        await self._send_json(msg)

    async def _persist_card(self, card, source_mode: str):
        if not self.db_session_id:
            return
        try:
            from ..database import async_session
            from ..models.meeting import MeetingSuggestion
            async with async_session() as db:
                db.add(MeetingSuggestion(
                    session_id=self.db_session_id,
                    text=card.text,
                    is_auto=(source_mode == "auto"),
                    suggestion_type=card.type,
                    trigger=card.trigger,
                    confidence=int(round(card.confidence * 100)),
                    source="strengthen" if source_mode == "strengthen" else "suggestion",
                    title=card.title or None,
                    why=card.why or None,
                    evidence_json=json.dumps([e.model_dump() for e in card.evidence], ensure_ascii=False),
                    card_json=card.model_dump_json(),
                    needs_user_check=card.needs_user_check,
                    source_mode=source_mode,
                    priority=card.priority,
                ))
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to persist suggestion card: {e}")

    # ---------------------------------------------------------------
    # JSON parsing helpers
    # ---------------------------------------------------------------

    def _parse_single_hint(self, raw: str, keyword: str = "") -> Dict[str, Any]:
        """Parse a single structured hint from LLM response."""
        try:
            cleaned = raw.strip()
            # Strip markdown code fences if present
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
            data = json.loads(cleaned)
            if isinstance(data, dict) and data.get("text"):
                return data
            if isinstance(data, list) and len(data) > 0:
                return data[0]
        except (json.JSONDecodeError, IndexError, KeyError):
            pass
        # Fallback: plain text as priority hint
        return {
            "type": "priority",
            "text": raw.strip(),
            "trigger": keyword or None,
            "confidence": None,
            "context_info": None,
        }

    def _parse_hints_array(self, raw: str) -> List[Dict[str, Any]]:
        """Parse an array of structured hints from LLM response."""
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
            data = json.loads(cleaned)
            if isinstance(data, list):
                return [h for h in data if isinstance(h, dict) and h.get("text")]
            if isinstance(data, dict) and data.get("text"):
                return [data]
        except (json.JSONDecodeError, IndexError, KeyError):
            pass
        # Fallback: single priority card with raw text
        return [{
            "type": "priority",
            "text": raw.strip(),
            "confidence": None,
            "context_info": None,
        }]

    async def _send_error(self, message: str):
        await self._send_json({"type": "error", "message": message})

    async def _send_status(self, message: str):
        await self._send_json({"type": "status", "message": message})

    async def _persist_suggestion(self, hint: Dict[str, Any], is_auto: bool,
                                   source: str = "suggestion"):
        """Persist suggestion to DB. Fire-and-forget."""
        if not self.db_session_id:
            return
        try:
            from ..database import async_session
            from ..models.meeting import MeetingSuggestion
            async with async_session() as db:
                record = MeetingSuggestion(
                    session_id=self.db_session_id,
                    text=hint.get("text", ""),
                    is_auto=is_auto,
                    suggestion_type=hint.get("type"),
                    trigger=hint.get("trigger"),
                    confidence=hint.get("confidence"),
                    context_info=hint.get("context_info"),
                    source=source,
                )
                db.add(record)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to persist suggestion: {e}")

    def cleanup(self):
        """Cleanup resources."""
        if self.transcription_service:
            self.transcription_service.stop()
        if self.audio_recorder:
            self.audio_recorder.stop()
        self.document_loader.clear()
        self._turn_assembler.reset()
        self._meeting_memory.reset()
