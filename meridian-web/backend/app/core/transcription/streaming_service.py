"""ElevenLabs Scribe v2 Realtime streaming transcription service.

Production-grade implementation:
- VAD commit strategy with tuned parameters
- Word-level timestamps and logprob preservation
- No fake diarization (speaker_id is null in realtime)
- Audio recording for batch finalization
- Structured error handling with reconnection
"""

import asyncio
import base64
import logging
from datetime import datetime
from typing import Callable, Optional, TYPE_CHECKING

from elevenlabs.client import AsyncElevenLabs
from elevenlabs.realtime.scribe import RealtimeAudioOptions, AudioFormat, CommitStrategy

from .models import (
    CommittedSegment, PartialTranscript, TranscriptWord,
    WordType, UNKNOWN_SPEAKER,
)

if TYPE_CHECKING:
    from ...services.audio_recorder import AudioRecorder

logger = logging.getLogger("meridian.elevenlabs")

# ElevenLabs error types that should NOT trigger reconnection
FATAL_ERRORS = {"auth_error", "invalid_api_key"}


class StreamingTranscriptionService:
    """Streaming transcription using ElevenLabs Scribe v2 Realtime.

    Key design decisions:
    - partial_transcript → PartialTranscript (UI preview only)
    - committed_transcript_with_timestamps → CommittedSegment (source of truth)
    - speaker_id is always null in realtime — no fake diarization
    - Audio duplicated to AudioRecorder for batch finalization
    """

    def __init__(
        self,
        api_key: str,
        audio_queue: asyncio.Queue,
        on_partial: Callable[[PartialTranscript], None],
        on_committed: Callable[[CommittedSegment], None],
        on_error: Optional[Callable[[str, str], None]] = None,
        model: str = "scribe_v2_realtime",
        language_code: Optional[str] = "ru",
        sample_rate: int = 16000,
        audio_recorder: Optional["AudioRecorder"] = None,
    ):
        self.api_key = api_key
        self.audio_queue = audio_queue
        self._on_partial_cb = on_partial
        self._on_committed_cb = on_committed
        self._on_error_cb = on_error
        self.model = model
        self.language_code = language_code
        self.sample_rate = sample_rate
        self.audio_recorder = audio_recorder

        self.client = AsyncElevenLabs(api_key=api_key)
        self.connection = None
        self.is_running = False
        self._fatal_error = False
        self._first_chunk_sent = False

    async def connect(self) -> bool:
        """Establish connection to ElevenLabs Scribe Realtime."""
        try:
            options_kwargs = dict(
                model_id=self.model,
                audio_format=AudioFormat.PCM_16000,
                sample_rate=self.sample_rate,
                include_timestamps=True,
                commit_strategy=CommitStrategy.VAD,
                # Production VAD tuning:
                # - silence_threshold 1.0s: wait for real pause before commit
                # - vad_threshold 0.5: less sensitive, filters noise better
                # - min_speech 250ms: ignore sub-250ms sounds (clicks, breaths)
                # - min_silence 300ms: brief pauses don't fragment speech
                # ElevenLabs warns: rapid commits degrade model performance
                vad_silence_threshold_secs=1.0,
                vad_threshold=0.5,
                min_speech_duration_ms=250,
                min_silence_duration_ms=300,
            )
            if self.language_code:
                options_kwargs["language_code"] = self.language_code

            options = RealtimeAudioOptions(**options_kwargs)
            self.connection = await self.client.speech_to_text.realtime.connect(options)
            logger.info("[ElevenLabs] Connected to Scribe v2 Realtime")
            return True
        except Exception as e:
            logger.error(f"[ElevenLabs] Connection error: {e}")
            return False

    async def disconnect(self):
        if self.connection:
            try:
                await self.connection.close()
            except Exception:
                pass
            self.connection = None

    async def run(self):
        """Main loop with reconnection and exponential backoff."""
        self.is_running = True
        reconnect_delay = 1

        while self.is_running and not self._fatal_error:
            try:
                if not await self.connect():
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)
                    continue

                reconnect_delay = 1
                self._first_chunk_sent = False  # resend context on reconnect

                self.connection.on("partial_transcript", self._handle_partial)
                self.connection.on(
                    "committed_transcript_with_timestamps",
                    self._handle_committed,
                )
                self.connection.on("error", self._handle_error)

                await asyncio.gather(
                    self._send_audio_loop(),
                    self._keep_alive(),
                )
            except Exception as e:
                logger.error(f"[ElevenLabs] Runtime error: {e}")
                await self.disconnect()
                if self.is_running and not self._fatal_error:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30)

    # Domain context hint sent with first audio chunk (max ~50 chars)
    PREVIOUS_TEXT = "Переговоры: строительство, КС-2, смета, договор"

    async def _send_audio_loop(self):
        """Read PCM from queue, send to ElevenLabs, write to recorder."""
        while self.is_running and self.connection:
            try:
                chunk = await asyncio.wait_for(
                    self.audio_queue.get(), timeout=0.1
                )
                if chunk:
                    _timestamp, audio_data = chunk
                    # Send to ElevenLabs as base64
                    audio_b64 = base64.b64encode(audio_data).decode("utf-8")
                    msg = {"audio_base_64": audio_b64}
                    # Send domain context with first chunk to improve accuracy
                    if not self._first_chunk_sent:
                        msg["previous_text"] = self.PREVIOUS_TEXT
                        self._first_chunk_sent = True
                    await self.connection.send(msg)
                    # Duplicate to audio recorder for batch finalization
                    if self.audio_recorder:
                        self.audio_recorder.write(audio_data)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[ElevenLabs] Send error: {e}")
                break

    async def _keep_alive(self):
        """Keep connection alive while running."""
        while self.is_running and self.connection:
            await asyncio.sleep(30)

    # --- Event handlers ---

    def _handle_partial(self, data):
        """partial_transcript → PartialTranscript (UI preview only)."""
        text = data.get("text", "")
        if not text:
            return
        partial = PartialTranscript(text=text)
        self._on_partial_cb(partial)

    def _handle_committed(self, data):
        """committed_transcript_with_timestamps → CommittedSegment (truth)."""
        text = data.get("text", "").strip()
        if not text:
            return

        raw_words = data.get("words", [])

        # Parse each word with full metadata
        words = []
        for w in raw_words:
            word_type_str = w.get("type", "word")
            try:
                word_type = WordType(word_type_str)
            except ValueError:
                word_type = WordType.WORD

            words.append(TranscriptWord(
                text=w.get("text", ""),
                start=w.get("start", 0.0),
                end=w.get("end", 0.0),
                type=word_type,
                logprob=w.get("logprob"),
            ))

        # Build committed segment — speaker_id is always unknown in realtime
        segment = CommittedSegment(
            text=text,
            words=words,
            speaker_id=UNKNOWN_SPEAKER,
        )

        self._on_committed_cb(segment)

    def _handle_error(self, error):
        """Handle ElevenLabs error events."""
        error_type = ""
        error_msg = str(error)

        if isinstance(error, dict):
            error_type = error.get("type", error.get("error", ""))
            error_msg = error.get("message", str(error))
        elif hasattr(error, "type"):
            error_type = getattr(error, "type", "")
            error_msg = getattr(error, "message", str(error))

        logger.error(f"[ElevenLabs] Error [{error_type}]: {error_msg}")

        if error_type in FATAL_ERRORS:
            self._fatal_error = True
            self.is_running = False

        if self._on_error_cb:
            self._on_error_cb(error_type, error_msg)

    def stop(self):
        self.is_running = False
