"""ElevenLabs Scribe v3 Live (realtime) — прямой WebSocket без SDK.

SDK (2.7x) не умеет multilang_mode, diarize, turn_prediction и keyterm_library, а при закрытии
сокета сервером не выходил из gather и не переподключался. Здесь:
- отдельные задачи-читатель и отправитель: любая из них закончилась → сессия закрыта и
  run() переподключается (backoff 1→30 с, connect с таймаутом);
- keepalive тишиной (сервер рвёт сессию через 15 с без сообщений);
- previous_text из реального текста встречи, keyterm_library — в первом чанке сессии;
- деградация опций, если сервер отвергает параметры (invalid_request / input_error);
- метки говорящих из diarized_transcript (DiarizationTracker).
Протокол, URL и вспомогательные классы — в elevenlabs_live_protocol.py.
"""

import asyncio
import base64
import json
import logging
import time
from datetime import datetime
from typing import Callable, Optional, TYPE_CHECKING

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidStatus

from .elevenlabs_live_protocol import (
    ALL_ERRORS, DEGRADE_ERRORS, FATAL_ERRORS, KEYTERMS_MAX, KEYTERMS_MAX_CHARS, RECONNECT_ERRORS, WS_URL,
    DiarizationTracker, LiveOptions, SessionTimeline,
    build_ws_url, clip_keyterm_library, silence_pcm, trim_previous_text,
)
from .models import (
    CommittedSegment, PartialTranscript, TranscriptWord,
    WordType, UNKNOWN_SPEAKER,
)

if TYPE_CHECKING:
    from ...services.audio_recorder import AudioRecorder

logger = logging.getLogger("meridian.elevenlabs")

# Уровни деградации опций: 0 — все, 1 — без «новых», 2 — ещё и без keyterms
MAX_DEGRADE_LEVEL = 2


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


class StreamingTranscriptionService:
    """Streaming transcription using ElevenLabs Scribe v3 Live (realtime).

    - partial_transcript → PartialTranscript (UI preview only)
    - committed_transcript_with_timestamps → CommittedSegment (source of truth), с языком
    - diarized_transcript → on_speaker(segment, label): метка говорящего поверх уже выданного сегмента
    - Audio duplicated to AudioRecorder for batch finalization
    """

    # Domain context hint для первого чанка, пока нет реального текста встречи (до ~50 символов)
    PREVIOUS_TEXT = "Переговоры: строительство, КС-2, смета, договор"

    def __init__(
        self,
        api_key: str,
        audio_queue: asyncio.Queue,
        on_partial: Callable[[PartialTranscript], None],
        on_committed: Callable[[CommittedSegment], None],
        on_error: Optional[Callable[[str, str], None]] = None,
        model: str = "scribe_v3_live",
        language_code: Optional[str] = None,
        sample_rate: int = 16000,
        audio_recorder: Optional["AudioRecorder"] = None,
        keyterms: Optional[list[str]] = None,
        keyterm_library: Optional[list[str]] = None,
        on_speaker: Optional[Callable[[CommittedSegment, str], None]] = None,
        options: Optional[LiveOptions] = None,
    ):
        self.api_key = api_key
        self.audio_queue = audio_queue
        self._on_partial_cb = on_partial
        self._on_committed_cb = on_committed
        self._on_error_cb = on_error
        self._on_speaker_cb = on_speaker
        self.model = model
        self.sample_rate = sample_rate
        self.audio_recorder = audio_recorder
        # Подсказки модели в query (до 50 штук по ≤20 символов — лимит Scribe v3 Live)
        self.keyterms = [t for t in (keyterms or []) if t and len(t) <= KEYTERMS_MAX_CHARS][:KEYTERMS_MAX]
        # Большой словарь для первого чанка сессии (до 10 000 терминов, ≤2 МБ)
        self.keyterm_library = clip_keyterm_library(keyterm_library or [])

        if options is None:
            from ...config import get_settings
            options = LiveOptions.from_settings(get_settings())
        self.options = options
        self.language_code = options.language if language_code is None else language_code

        # Подменяемые в тестах: адрес, паузы и пороги
        self.ws_url = WS_URL
        self.connect_timeout = 10.0
        self.backoff_start = 1.0
        self.backoff_max = 30.0
        self.stale_audio_secs = 30.0
        self.poll_secs = 0.1

        self.is_running = False
        self._fatal_error = False
        self._degrade_level = 0
        # Первый committed на текущем уровне опций = уровень принят; позже ошибки его не снижают
        self._level_accepted = False
        self._session_no = 0
        self._timeline = SessionTimeline()
        self._tracker = DiarizationTracker(0)
        self._recent_text = ""  # реальный committed-текст встречи — для previous_text
        self._dropped_stale = 0
        # состояние текущей сессии
        self._first_chunk_sent = False
        self._got_traffic = False
        self._degrade_now = False
        self._last_audio_mono = 0.0

    # --- параметры сессии ---

    @property
    def _active_options(self) -> LiveOptions:
        return self.options if self._degrade_level == 0 else self.options.degraded()

    def _session_url(self) -> str:
        return build_ws_url(
            self.ws_url, model=self.model, sample_rate=self.sample_rate,
            options=self._active_options, language_code=self.language_code,
            keyterms=self.keyterms if self._degrade_level < 2 else [],
            send_keepalive=self._degrade_level == 0,
        )

    # --- главный цикл ---

    async def run(self):
        """Main loop: подключение → обмен → при любом завершении сессии реконнект с backoff."""
        self.is_running = True
        delay = self.backoff_start

        while self.is_running and not self._fatal_error:
            self._begin_session()
            ws = None
            try:
                # С прода ElevenLabs напрямую = геоблок (302 на geo-restriction): только через прокси.
                # Нет ELEVENLABS_PROXY_URL — прокси из окружения (поведение websockets по умолчанию).
                from ...config import get_settings
                ws = await ws_connect(
                    self._session_url(),
                    additional_headers={"xi-api-key": self.api_key},
                    open_timeout=self.connect_timeout,
                    proxy=get_settings().elevenlabs_proxy_url or True,
                )
                logger.info("[ElevenLabs] Connected to Scribe v3 Live (level %d, session %d)",
                            self._degrade_level, self._session_no)
                await self._run_session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("[ElevenLabs] Session error: %s: %s", type(e).__name__, e)
                # Рукопожатие отвергнуто как «плохой запрос» — тот же путь деградации опций
                if (isinstance(e, InvalidStatus) and e.response.status_code in (400, 422)
                        and not self._level_accepted and self._degrade_level < MAX_DEGRADE_LEVEL):
                    self._degrade_level += 1
                    self._degrade_now = True
                    logger.warning("[ElevenLabs] HTTP %s при подключении — уровень опций %d",
                                   e.response.status_code, self._degrade_level)
            finally:
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
            if not (self.is_running and not self._fatal_error):
                break
            if self._dropped_stale:
                logger.warning("[ElevenLabs] Выброшено устаревших чанков (>%.0f с): %d",
                               self.stale_audio_secs, self._dropped_stale)
                self._dropped_stale = 0
            if self._degrade_now:
                delay = self.backoff_start  # шаг деградации — сразу, без паузы
                continue
            if self._got_traffic:
                delay = self.backoff_start
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.backoff_max)

    def _begin_session(self) -> None:
        self._session_no += 1
        self._tracker = DiarizationTracker(self._session_no)
        self._timeline.start_session()
        self._first_chunk_sent = False
        self._got_traffic = False
        self._degrade_now = False
        self._last_audio_mono = time.monotonic()

    async def _run_session(self, ws) -> None:
        """Читатель и отправитель параллельно; закончилась любая — гасим обе."""
        tasks = [
            asyncio.create_task(self._reader(ws)),
            asyncio.create_task(self._sender(ws)),
        ]
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.cancelled() and task.exception() is not None:
                    logger.error("[ElevenLabs] Session task failed: %s: %s",
                                 type(task.exception()).__name__, task.exception())
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- отправка ---

    def _first_chunk_extras(self) -> dict:
        extras: dict = {"previous_text": trim_previous_text(self._recent_text) or self.PREVIOUS_TEXT}
        if self._active_options.keyterm_library and self.keyterm_library:
            extras["keyterm_library"] = self.keyterm_library
        return extras

    async def _send_chunk(self, ws, pcm: bytes) -> None:
        msg = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(pcm).decode("ascii"),
            "commit": False,
            "sample_rate": self.sample_rate,
        }
        # previous_text и keyterm_library допустимы только в первом чанке сессии (в т.ч. тишине)
        if not self._first_chunk_sent:
            msg.update(self._first_chunk_extras())
        await ws.send(json.dumps(msg, ensure_ascii=False))
        self._first_chunk_sent = True
        self._last_audio_mono = time.monotonic()

    async def _sender(self, ws) -> None:
        """PCM из очереди → ElevenLabs и recorder; при простое — тишина-keepalive."""
        keepalive = self.options.keepalive_secs
        while self.is_running:
            if time.monotonic() - self._last_audio_mono >= keepalive:
                silence = silence_pcm(self.sample_rate)
                await self._send_chunk(ws, silence)
                self._timeline.on_silence_sent(len(silence) / 2 / self.sample_rate)
            try:
                item = await asyncio.wait_for(self.audio_queue.get(), timeout=self.poll_secs)
            except asyncio.TimeoutError:
                continue
            if not item:
                continue
            ts, audio_data = item
            seconds = len(audio_data) / 2 / self.sample_rate
            if self.audio_recorder:  # запись полная, в т.ч. для выброшенных ниже чанков
                self.audio_recorder.write(audio_data)
            try:
                if isinstance(ts, datetime) and (datetime.now() - ts).total_seconds() > self.stale_audio_secs:
                    self._dropped_stale += 1
                    continue
                await self._send_chunk(ws, audio_data)
                self._timeline.on_real_sent(seconds)
            finally:
                self._timeline.advance_recorded(seconds)  # чанк уже в записи, как бы ни закончилась отправка

    # --- приём ---

    async def _reader(self, ws) -> None:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning("[ElevenLabs] Невалидное сообщение сервера")
                continue
            if not isinstance(data, dict):
                continue
            try:
                if self._handle_message(data):
                    return  # сессию нужно закончить (ошибка сервера) → реконнект
            except Exception:
                logger.exception("[ElevenLabs] Ошибка обработки сообщения %s", data.get("message_type"))

    def _handle_message(self, data: dict) -> bool:
        """Обработать сообщение сервера. True — завершить сессию."""
        mtype = data.get("message_type", "")
        if mtype in ALL_ERRORS:
            return self._handle_error(mtype, str(data.get("error", "")))
        if mtype in ("partial_transcript", "committed_transcript", "committed_transcript_with_timestamps"):
            self._got_traffic = True
        if mtype == "partial_transcript":
            self._handle_partial(data)
        elif mtype == "committed_transcript":
            self._tracker.note_plain_commit(data.get("segment_index"), data.get("text", ""))
        elif mtype == "committed_transcript_with_timestamps":
            self._handle_committed(data)
        elif mtype == "diarized_transcript":
            self._emit_speaker(self._tracker.on_diarized(data))
        elif mtype == "speakers_merged":
            for hit in self._tracker.on_merged(data.get("from_speaker_id"), data.get("to_speaker_id")):
                self._emit_speaker(hit)
        elif mtype == "warning":
            logger.warning("[ElevenLabs] Warning: %s", data.get("warning", ""))
        elif mtype == "session_started":
            logger.info("[ElevenLabs] Session started")
        return False

    def _handle_partial(self, data: dict) -> None:
        text = data.get("text", "")
        if text:  # пустой partial — keepalive сервера
            self._on_partial_cb(PartialTranscript(text=text))

    def _handle_committed(self, data: dict) -> None:
        """committed_transcript_with_timestamps → CommittedSegment (truth)."""
        text = (data.get("text") or "").strip()
        index = self._tracker.next_index(data.get("segment_index"), text)
        if not text:
            return
        if not self._level_accepted:
            self._level_accepted = True
            logger.info("[ElevenLabs] Уровень опций %d принят (первый committed)", self._degrade_level)

        words = []
        for w in data.get("words") or []:
            try:
                word_type = WordType(w.get("type", "word"))
            except ValueError:
                word_type = WordType.WORD
            words.append(TranscriptWord(
                text=w.get("text", ""),
                start=self._timeline.to_meeting(_num(w.get("start"))),
                end=self._timeline.to_meeting(_num(w.get("end"))),
                type=word_type,
                logprob=w.get("logprob"),
            ))

        language = data.get("language_code")
        segment = CommittedSegment(
            text=text,
            words=words,
            speaker_id=UNKNOWN_SPEAKER,
            language=language if isinstance(language, str) and language else None,
        )
        self._recent_text = f"{self._recent_text} {text}"[-300:]
        self._on_committed_cb(segment)
        # метка говорящего могла прийти раньше сегмента
        self._emit_speaker(self._tracker.register(index, segment, text))

    def _emit_speaker(self, hit: Optional[tuple[CommittedSegment, str]]) -> None:
        if hit is not None and self._on_speaker_cb:
            segment, label = hit
            self._on_speaker_cb(segment, label)

    def _handle_error(self, error_type: str, error_msg: str) -> bool:
        """Ошибка сервера. True — сессию закрываем (реконнект или остановка)."""
        # Параметры отвергнуты до первого committed — пробуем с меньшим набором опций
        if (error_type in DEGRADE_ERRORS and not self._level_accepted
                and self._degrade_level < MAX_DEGRADE_LEVEL):
            self._degrade_level += 1
            self._degrade_now = True
            logger.warning(
                "[ElevenLabs] Сервер отверг параметры [%s]: %s — переподключение с уровнем %d "
                "(%s)", error_type, error_msg, self._degrade_level,
                "без новых опций" if self._degrade_level == 1 else "без keyterms",
            )
            return True

        logger.error("[ElevenLabs] Error [%s]: %s", error_type, error_msg)
        if error_type in FATAL_ERRORS:
            self._fatal_error = True
            self.is_running = False
        if self._on_error_cb:
            self._on_error_cb(error_type, error_msg)
        return error_type in FATAL_ERRORS or error_type in RECONNECT_ERRORS or error_type in DEGRADE_ERRORS

    def stop(self):
        self.is_running = False
