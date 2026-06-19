"""Per-user meeting session manager.

Manages transcription, AI hints, audio recording, and batch finalization.
Each user gets their own SessionManager with independent state.
"""

import asyncio
import json
import logging
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
from ..core.context.meeting_memory import MeetingMemory
from ..core.llm.suggestion_prompts import (
    build_auto_cards_prompt, build_manual_cards_prompt, build_strengthen_prompt,
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
        self.speaker_roles: Dict[str, str] = {}  # display_name → side
        # Этап 8: segment-level коррекции диаризации (segment_id → {side, corrected_speaker_label})
        self.speaker_segment_corrections: Dict[str, dict] = {}

        # Stored API keys for batch finalization
        self._elevenlabs_key: Optional[str] = None

        # Custom suggestion types / trigger keywords (per-user overrides)
        self._valid_suggestion_types = set(DEFAULT_VALID_SUGGESTION_TYPES)
        self._keyword_status = dict(DEFAULT_KEYWORD_STATUS)

        # Turn assembler (merges consecutive same-speaker segments)
        self._turn_assembler = TurnAssembler()

        # Meeting memory (three-layer context for long meetings)
        self._meeting_memory = MeetingMemory()

        # Event detector (rule-based negotiation events)
        self._event_detector = EventDetector()

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
        effective = corrected_label or original
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
                              diarization: bool = True):
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
        if stt_provider == "deepgram":
            from ..core.transcription.deepgram_streaming_service import (
                DeepgramStreamingTranscriptionService,
            )
            key = api_keys.get("deepgram", "")
            self.transcription_service = DeepgramStreamingTranscriptionService(
                api_key=key,
                audio_queue=self.audio_queue,
                message_callback=self._on_legacy_transcript,
                diarization=diarization,
            )
        elif stt_provider == "elevenlabs":
            from ..core.transcription.streaming_service import (
                StreamingTranscriptionService,
            )
            key = api_keys.get("elevenlabs", "")
            self.transcription_service = StreamingTranscriptionService(
                api_key=key,
                audio_queue=self.audio_queue,
                on_partial=self._on_partial,
                on_committed=self._on_committed,
                on_error=self._on_stt_error,
                audio_recorder=self.audio_recorder,
            )
        elif stt_provider == "gemini":
            from ..core.transcription.gemini_streaming_service import (
                GeminiStreamingTranscriptionService,
            )
            key = api_keys.get("gemini", "")
            self.transcription_service = GeminiStreamingTranscriptionService(
                api_key=key,
                audio_queue=self.audio_queue,
                message_callback=self._on_legacy_transcript,
            )
        elif stt_provider == "speechmatics":
            from ..core.transcription.speechmatics_streaming_service import (
                SpeechmaticsStreamingTranscriptionService,
            )
            key = api_keys.get("speechmatics", "")
            self.transcription_service = SpeechmaticsStreamingTranscriptionService(
                api_key=key,
                audio_queue=self.audio_queue,
                message_callback=self._on_legacy_transcript,
            )
        else:
            await self._send_error(f"Unknown STT provider: {stt_provider}")
            self.is_listening = False
            return

        # Start transcription in background task
        self._transcription_task = asyncio.create_task(
            self.transcription_service.run()
        )
        await self._send_status("Прослушивание активно...")

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
