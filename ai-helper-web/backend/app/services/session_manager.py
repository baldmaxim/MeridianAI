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
from ..core.llm.prompts import PromptBuilder
from ..core.transcription.models import (
    TranscriptSegment, CommittedSegment, PartialTranscript,
    UNKNOWN_SPEAKER,
)
from .audio_recorder import AudioRecorder

logger = logging.getLogger("ai_helper.session")

# Global registry of active sessions
_sessions: Dict[int, "SessionManager"] = {}

# AI hint debounce settings
HINT_DEBOUNCE_SEC = 3.0
HINT_COOLDOWN_SEC = 30.0
MIN_SEGMENTS_FOR_HINT = 2

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

        # State
        self.is_listening = False
        self._transcription_task: Optional[asyncio.Task] = None

        # Committed segment store (source of truth during live session)
        self._committed_segments: List[CommittedSegment] = []

        # AI hint debounce
        self._hint_buffer: List[CommittedSegment] = []
        self._hint_debounce_task: Optional[asyncio.Task] = None
        self._auto_trigger_cooldown: Dict[str, float] = {}

        # Speaker
        self.speaker_mapping: Dict[str, str] = {}
        self.current_speaker: Optional[str] = None

        # Stored API keys for batch finalization
        self._elevenlabs_key: Optional[str] = None

        # Custom suggestion types / trigger keywords (per-user overrides)
        self._valid_suggestion_types = set(DEFAULT_VALID_SUGGESTION_TYPES)
        self._keyword_status = dict(DEFAULT_KEYWORD_STATUS)

        # WebSocket send callback
        self._ws_send: Optional[Callable] = None

    def set_ws_send(self, send_func: Callable):
        """Set WebSocket send function for pushing messages to client."""
        self._ws_send = send_func

    def configure_llm(self, api_key: str, model: str, temperature: float):
        """Configure LLM client with API key from database."""
        self.llm_client = LLMClient(
            api_key=api_key, model=model, temperature=temperature
        )
        # Apply role system prompt if role was set before LLM
        if self.role_data and self.llm_client:
            self.llm_client.set_system_prompt(self.prompt_builder.system_prompt)

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

        # Schedule debounced AI hint check
        self._schedule_hint_check(segment)

    def _on_stt_error(self, error_type: str, error_msg: str):
        """Handle STT error events."""
        if self._ws_send:
            asyncio.create_task(self._send_error(
                f"STT ошибка [{error_type}]: {error_msg}"
            ))

    # ---------------------------------------------------------------
    # Legacy callback (Deepgram / Gemini backward compat)
    # ---------------------------------------------------------------

    def _on_legacy_transcript(self, segment: TranscriptSegment, is_partial: bool):
        """Legacy callback from Deepgram/Gemini services."""
        if not is_partial:
            # Apply speaker mapping
            if segment.speaker in self.speaker_mapping:
                segment.speaker = self.speaker_mapping[segment.speaker]
            elif self.current_speaker:
                segment.speaker = self.current_speaker

            self.context_analyzer.add_segment(segment)

            # Also write to audio recorder if not ElevenLabs
            # (ElevenLabs writes in streaming_service._send_audio_loop)

        # Send to client
        if self._ws_send:
            asyncio.create_task(self._send_transcript(segment, is_partial))

            # Check auto-triggers for final segments
            if not is_partial:
                asyncio.create_task(self._check_legacy_auto_triggers(segment.text))

    # ---------------------------------------------------------------
    # AI Hint System (debounced)
    # ---------------------------------------------------------------

    def _schedule_hint_check(self, segment: CommittedSegment):
        """Add segment to buffer, reset debounce timer."""
        self._hint_buffer.append(segment)
        if self._hint_debounce_task and not self._hint_debounce_task.done():
            self._hint_debounce_task.cancel()
        self._hint_debounce_task = asyncio.create_task(self._debounced_hint_check())

    async def _debounced_hint_check(self):
        """Wait for pause, then check buffered segments for keywords."""
        await asyncio.sleep(HINT_DEBOUNCE_SEC)

        if not self._hint_buffer or not self.llm_client:
            return
        if len(self._committed_segments) < MIN_SEGMENTS_FOR_HINT:
            return

        # Aggregate buffer text
        batch_text = " ".join(s.text for s in self._hint_buffer)
        self._hint_buffer.clear()

        keywords = self.context_analyzer.detect_trigger_keywords(batch_text)
        now = time.time()

        triggered_keyword = None
        for kw in keywords:
            last_trigger = self._auto_trigger_cooldown.get(kw, 0)
            if now - last_trigger >= HINT_COOLDOWN_SEC:
                triggered_keyword = kw
                self._auto_trigger_cooldown[kw] = now
                break

        if not triggered_keyword:
            return

        # Send analysis status
        status_msg = self._keyword_status.get(
            triggered_keyword, f"Анализирую: «{triggered_keyword}»..."
        )
        await self._send_analysis_status(status_msg)

        # Build structured prompt
        recent = self._get_committed_context(minutes=5)
        doc_context = (
            self.document_loader.get_context_for_prompt()
            if self.document_loader.has_context() else ""
        )
        prompt = self.prompt_builder.build_auto_suggestion_structured_prompt(
            keyword=triggered_keyword,
            recent_dialog=recent,
            document_context=doc_context,
        )

        raw = await self.llm_client.get_suggestion_async(prompt, max_tokens=200)
        if raw:
            hint = self._parse_single_hint(raw, triggered_keyword)
            await self._send_structured_suggestion(hint, is_auto=True)

        await self._send_analysis_status(None)

    async def _check_legacy_auto_triggers(self, text: str):
        """Legacy auto-trigger check for Deepgram/Gemini."""
        if not self.llm_client:
            return

        keywords = self.context_analyzer.detect_trigger_keywords(text)
        now = time.time()

        for keyword in keywords:
            last_trigger = self._auto_trigger_cooldown.get(keyword, 0)
            if now - last_trigger < HINT_COOLDOWN_SEC:
                continue

            self._auto_trigger_cooldown[keyword] = now

            status_msg = self._keyword_status.get(
                keyword, f"Анализирую: «{keyword}»..."
            )
            await self._send_analysis_status(status_msg)

            recent = self.context_analyzer.get_recent_context(5)
            doc_context = (
                self.document_loader.get_context_for_prompt()
                if self.document_loader.has_context() else ""
            )
            prompt = self.prompt_builder.build_auto_suggestion_structured_prompt(
                keyword=keyword, recent_dialog=recent,
                document_context=doc_context,
            )

            raw = await self.llm_client.get_suggestion_async(
                prompt, max_tokens=200
            )
            if raw:
                hint = self._parse_single_hint(raw, keyword)
                await self._send_structured_suggestion(hint, is_auto=True)

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
        await self._send_analysis_status("Формирую тактические подсказки...")

        context = self._get_committed_context(minutes=5)
        if not context:
            context = self.context_analyzer.get_context_by_time(5)
        if not context:
            await self._send_error("Нет данных для анализа")
            await self._send_analysis_status(None)
            await self._send_json({"type": "suggestion_loading", "loading": False})
            return

        doc_context = self.document_loader.get_document_context()

        prompt = self.prompt_builder.build_tactical_hints_prompt(
            recent_dialog=context,
            document_context=doc_context,
            topic=self.document_loader.meeting_topic,
            notes=self.document_loader.meeting_notes,
            negotiation_type=self.negotiation_type,
            meeting_role=self.meeting_role,
            opponent_weaknesses=self.opponent_weaknesses,
        )

        raw = await self.llm_client.get_suggestion_async(prompt, max_tokens=600)
        if raw:
            hints = self._parse_hints_array(raw)
            for hint in hints:
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

        context = self._get_committed_context(minutes=5)
        if not context:
            context = self.context_analyzer.get_context_by_time(5)
        if not context:
            await self._send_error("Нет данных для анализа")
            await self._send_analysis_status(None)
            await self._send_json({"type": "strengthen_loading", "loading": False})
            return

        doc_context = self.document_loader.get_document_context()
        prompt = self.prompt_builder.build_strengthen_position_prompt(
            full_transcript=context,
            document_context=doc_context,
            topic=self.document_loader.meeting_topic,
            notes=self.document_loader.meeting_notes,
            negotiation_type=self.negotiation_type,
            meeting_role=self.meeting_role,
            opponent_weaknesses=self.opponent_weaknesses,
        )

        full_text_parts: list[str] = []
        async for chunk_text in self.llm_client.get_suggestion_streaming_async(
            prompt, max_tokens=1500
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

            # Send to client
            await self._send_json({
                "type": "batch_finalized",
                "segments": [s.to_wire_full() for s in segments],
            })
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
            speaker = seg.speaker_label or seg.speaker_id
            line = f"[{ts}] {speaker}: {seg.text}"
            if seg.is_low_confidence:
                line += "  [НИЗКАЯ УВЕРЕННОСТЬ]"
            lines.append(line)

        return "\n".join(lines)

    @property
    def committed_segments(self) -> List[CommittedSegment]:
        """Public access to committed segments (read-only intent)."""
        return self._committed_segments

    # ---------------------------------------------------------------
    # WebSocket message helpers
    # ---------------------------------------------------------------

    async def _send_json(self, data: dict):
        if self._ws_send:
            await self._ws_send(data)

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
