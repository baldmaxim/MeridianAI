"""Multi-channel live STT shadow session (Этап 9.6).

Оркестрирует mux → realtime provider → нормализованный live-candidate. Это ДИАГНОСТИКА:
основной STT/подсказки/transcript/Context Pack/Conversation Tree не затрагиваются, ничего
не сохраняется в БД/диск/S3. Один provider-сокет на сессию, без reconnect, bounded queue,
bounded finals. API key/raw response/PCM не логируются и не попадают в state.
"""

import asyncio
import hashlib
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .realtime_multi_channel_mux import (
    RealtimeMultiChannelMuxer,
    RealtimeMuxChannel,
    RealtimeMuxError,
    RealtimeMuxScheduler,
)
from .realtime_multi_channel_provider import (
    ERR_BACKPRESSURE,
    RealtimeMultiChannelProviderError,
    RealtimeProviderResult,
)

logger = logging.getLogger("meridian.live_mc")

LiveMultiChannelStatus = Literal[
    "idle", "buffering", "connecting", "streaming", "degraded", "stopping", "stopped", "failed",
]

_NON_TERMINAL = {"idle", "buffering", "connecting", "streaming", "degraded"}


@dataclass(frozen=True)
class LiveMultiChannelSegment:
    segment_id: str
    session_id: str
    channel_index: int
    channels_count: int
    track_id: str
    channel_label: str
    side: str | None
    transcript: str
    confidence: float | None
    provider_start: float
    provider_end: float
    start_server_ms: int
    end_server_ms: int
    is_final: bool
    speech_final: bool
    words: tuple = ()


def live_multi_channel_segment_to_source_candidate(segment) -> dict | None:
    """Этап 10: per-channel LiveMultiChannelSegment → source attribution candidate payload (или None).

    Per-channel поток = изолированный source (одна дорожка = один канал/источник). Кандидат несёт
    text (только для технического match) + channel/source + timestamps. `side`/side_hint НЕ
    включаем (это не сторона переговоров). speaker_label здесь НЕТ — он придёт из committed-сегмента
    при reconcile. Возвращает None, если нет source/channel или нет ни текста, ни таймстемпов."""
    def _g(*names):
        for n in names:
            v = segment.get(n) if isinstance(segment, dict) else getattr(segment, n, None)
            if v is not None:
                return v
        return None
    text = _g("transcript", "text")
    start_ms = _g("start_server_ms", "start_ms")
    end_ms = _g("end_server_ms", "end_ms")
    track = _g("track_id")
    channel = _g("channel_label", "label")
    if not track and not channel:
        return None
    if not (text and str(text).strip()) and (start_ms is None or end_ms is None):
        return None
    conf = _g("confidence")
    return {
        "text": text,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "audio_source_id": track or channel,
        "channel_label": channel,
        "source_is_isolated": True,  # per-channel pipeline (не общий room-mic)
        "source_kind": "multi_channel",
        "attribution_source": "multi_source_segment",
        "attribution_confidence": (conf if conf is not None else 0.75),
        "candidate_id": _g("segment_id", "id"),
        "candidate_pipeline": "multi_channel_live",
    }


@dataclass
class MultiChannelLiveState:
    session_id: str
    meeting_id: int
    owner_user_id: int
    status: LiveMultiChannelStatus
    provider: str
    model: str
    language: str
    channels: tuple
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    start_frame_index: int | None = None
    start_server_ms: int | None = None
    chunks_sent: int = 0
    frames_sent: int = 0
    bytes_sent: int = 0
    provider_queue_depth: int = 0
    provider_request_id: str | None = None
    latest_interim_by_channel: dict = field(default_factory=dict)
    final_segments: deque = field(default_factory=deque)
    silence_ratio_by_channel: list = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class GlobalLiveLimiter:
    """Глобальный лимит одновременных live-сессий (по процессу)."""

    def __init__(self) -> None:
        self._active = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self, max_sessions: int) -> bool:
        async with self._lock:
            if self._active >= max(1, max_sessions):
                return False
            self._active += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            if self._active > 0:
                self._active -= 1


live_limiter = GlobalLiveLimiter()


def _seg_id(session_id: str, channel_index: int, start_ms: int, end_ms: int, text: str) -> str:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"mclive:{session_id}:{channel_index}:{start_ms}:{end_ms}:{h}"


class MultiChannelLiveSession:
    def __init__(self, *, meeting_id: int, owner_user_id: int, ingest, broadcast,
                 provider, channels: tuple, settings, on_final_segment=None,
                 on_terminal=None) -> None:
        self.session_id = uuid.uuid4().hex[:16]
        self._ingest = ingest
        self._broadcast = broadcast        # async def(event: dict)
        self._provider = provider
        self._settings = settings
        # Этап 9.7: async callback при новом FINAL сегменте (для reconciliation).
        # interim его не вызывает; ошибка callback не ломает provider-сессию.
        self._on_final_segment = on_final_segment
        # Этап 9.8: async callback при терминальном состоянии (stopped/failed) — ровно один
        # раз. Используется cutover-контроллером для авто-fallback при сбое promoted-сессии.
        self._on_terminal = on_terminal
        self._terminal_notified = False
        self._channels = channels
        self._channel_by_index = {c.channel_index: c for c in channels}
        self.sample_rate = settings.secondary_audio_shadow_target_sample_rate or 16000
        self.frame_ms = settings.multi_source_ingest_frame_ms

        self._muxer = RealtimeMultiChannelMuxer(
            ingest=ingest, channels=channels, sample_rate=self.sample_rate, frame_ms=self.frame_ms,
            playout_delay_ms=settings.multi_channel_live_playout_delay_ms,
            send_chunk_ms=settings.multi_channel_live_send_chunk_ms,
        )
        self._queue: asyncio.Queue = asyncio.Queue(
            maxsize=settings.multi_channel_live_send_queue_chunks)
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._last_audio_monotonic = 0.0
        self._last_interim_broadcast = 0.0
        self._last_state_broadcast = 0.0
        self._slot_acquired = False

        self.state = MultiChannelLiveState(
            session_id=self.session_id, meeting_id=meeting_id, owner_user_id=owner_user_id,
            status="idle", provider=settings.multi_channel_live_provider,
            model=settings.multi_channel_live_model, language=settings.multi_channel_live_language,
            channels=channels,
            final_segments=deque(maxlen=settings.multi_channel_live_max_final_segments),
            silence_ratio_by_channel=[0.0] * len(channels),
        )

    # --- lifecycle ---

    async def start(self) -> None:
        max_sessions = self._settings.multi_channel_live_max_global_sessions
        if not await live_limiter.try_acquire(max_sessions):
            await self.fail("TOO_MANY_SESSIONS", "Достигнут лимит live-сессий")
            return
        self._slot_acquired = True
        try:
            self.state.status = "buffering"
            now_ms = int(time.time() * 1000)
            start_index = self._muxer.choose_start_index(
                now_server_ms=now_ms,
                min_prebuffer_ms=self._settings.multi_channel_live_min_prebuffer_ms,
            )
            self.state.start_frame_index = start_index
            self.state.start_server_ms = start_index * self.frame_ms

            self.state.status = "connecting"
            await asyncio.wait_for(
                self._provider.connect(
                    channel_count=len(self._channels), sample_rate=self.sample_rate,
                    model=self.state.model, language=self.state.language,
                    on_result=self._on_result, on_error=self._on_provider_error,
                ),
                timeout=self._settings.multi_channel_live_start_timeout_seconds,
            )

            self._running = True
            self.state.started_at = datetime.utcnow()
            self.state.status = "streaming"
            sched = RealtimeMuxScheduler(
                muxer=self._muxer, start_frame_index=start_index,
                send_chunk_ms=self._settings.multi_channel_live_send_chunk_ms,
            )
            self._tasks = [
                asyncio.create_task(self._scheduler_loop(sched)),
                asyncio.create_task(self._sender_loop()),
                asyncio.create_task(self._keepalive_loop()),
                asyncio.create_task(self._watchdog_loop()),
            ]
            await self._broadcast_state()
        except (RealtimeMuxError, RealtimeMultiChannelProviderError) as e:
            await self.fail(e.code, str(e))
        except asyncio.TimeoutError:
            await self.fail("PROVIDER_TIMEOUT", "Провайдер не ответил вовремя")
        except Exception:
            await self.fail("INTERNAL_ERROR", "Внутренняя ошибка live-сессии")

    async def _scheduler_loop(self, sched: RealtimeMuxScheduler) -> None:
        sched.begin()
        try:
            while self._running:
                delay = sched.next_chunk_blocking_delay()
                if delay > 0:
                    await asyncio.sleep(delay)
                if not self._running:
                    break
                chunk = sched.build_next()
                try:
                    self._queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    await self.fail(ERR_BACKPRESSURE, "Очередь провайдера переполнена")
                    return
                self.state.chunks_sent += 1
                self.state.frames_sent += chunk.frame_count
                self.state.provider_queue_depth = self._queue.qsize()
                self.state.silence_ratio_by_channel = self._muxer.channel_silence_ratios()
        except asyncio.CancelledError:
            raise
        except RealtimeMuxError as e:
            await self.fail(e.code, str(e))
        except KeyError:
            await self.fail("TRACK_NOT_FOUND", "Канал больше не доступен в ingest")
        except Exception as e:
            logger.debug("mc-live scheduler task died: %s", type(e).__name__)
            await self.fail("INTERNAL_ERROR", "Сбой планировщика live-сессии")

    async def _sender_loop(self) -> None:
        try:
            while self._running:
                try:
                    chunk = await asyncio.wait_for(self._queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if chunk is None:
                    break
                await self._provider.send_audio(chunk.pcm16_interleaved)
                self.state.bytes_sent += len(chunk.pcm16_interleaved)
                self.state.provider_queue_depth = self._queue.qsize()
                self._last_audio_monotonic = time.monotonic()
        except asyncio.CancelledError:
            raise
        except RealtimeMultiChannelProviderError as e:
            await self.fail(e.code, str(e))
        except Exception:
            await self.fail("INTERNAL_ERROR", "Сбой отправки аудио провайдеру")

    async def _keepalive_loop(self) -> None:
        interval = self._settings.multi_channel_live_keepalive_seconds
        try:
            while self._running:
                await asyncio.sleep(interval)
                if time.monotonic() - self._last_audio_monotonic > interval:
                    await self._provider.keepalive()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("mc-live keepalive task error: %s", type(e).__name__)

    async def _watchdog_loop(self) -> None:
        grace = self._settings.multi_channel_live_track_stale_grace_ms
        sec_stop = self._settings.multi_channel_live_secondary_silence_stop_ms
        warn_ratio = self._settings.multi_channel_live_silence_warn_ratio
        max_session_s = self._settings.multi_channel_live_max_session_seconds
        try:
            while self._running:
                await asyncio.sleep(1.0)
                silent_ms = self._muxer.consecutive_silence_ms()       # windowed (хвост)
                ratios = self._muxer.channel_silence_ratios()
                degraded = False
                for c in self._channels:
                    ci = c.channel_index
                    sm = silent_ms[ci] if ci < len(silent_ms) else 0
                    if c.source_kind == "primary":
                        # основной канал замолчал дольше grace → останавливаем shadow (fail)
                        if sm > grace:
                            await self.fail("PRIMARY_STALE", "Основной канал замолчал")
                            return
                    else:  # secondary
                        if sm > sec_stop:
                            await self.stop()                          # долгая тишина → остановка
                            return
                        if sm > grace or (ci < len(ratios) and ratios[ci] >= warn_ratio):
                            degraded = True
                if degraded and self.state.status == "streaming":
                    self.state.status = "degraded"
                    await self._broadcast_state()
                elif not degraded and self.state.status == "degraded":
                    self.state.status = "streaming"
                    await self._broadcast_state()
                if self.state.started_at:
                    elapsed = (datetime.utcnow() - self.state.started_at).total_seconds()
                    if elapsed > max_session_s:
                        await self.stop()
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("mc-live watchdog task error: %s", type(e).__name__)

    async def stop(self) -> None:
        if self.state.status in ("stopped", "failed"):
            return
        self.state.status = "stopping"
        self._running = False
        await self._cancel_tasks()
        try:
            await self._provider.close(finalize=True)
        except Exception:
            pass
        self._drain_queue()
        self.state.stopped_at = datetime.utcnow()
        self.state.status = "stopped"
        self.state.provider_request_id = getattr(self._provider, "request_id", None)
        await self._release_slot()
        await self._broadcast_state()
        await self._notify_terminal()

    async def fail(self, code: str, message: str) -> None:
        if self.state.status == "failed":
            return
        self._running = False
        self.state.status = "failed"
        self.state.error_code = code
        self.state.error_message = message  # уже безопасные строки
        await self._cancel_tasks()
        try:
            await self._provider.close(finalize=False)
        except Exception:
            pass
        self._drain_queue()
        self.state.stopped_at = datetime.utcnow()
        await self._release_slot()
        await self._broadcast_state()
        await self._notify_terminal()

    async def _notify_terminal(self) -> None:
        # ровно один раз; ошибка callback не должна ломать teardown live-сессии
        if self._terminal_notified or self._on_terminal is None:
            return
        self._terminal_notified = True
        try:
            await self._on_terminal()
        except Exception:
            logger.debug("mc-live on_terminal callback error")

    async def clear_results(self) -> None:
        self.state.final_segments.clear()
        self.state.latest_interim_by_channel.clear()
        await self._broadcast_state()

    async def _cancel_tasks(self) -> None:
        # fail()/stop() могут вызываться ИЗНУТРИ одной из задач (scheduler/sender) —
        # текущую задачу не отменяем и не ждём (иначе await самого себя).
        current = asyncio.current_task()
        targets = [t for t in self._tasks if t is not current]
        for t in targets:
            t.cancel()
        for t in targets:
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("mc-live task teardown error: %s", type(e).__name__)
        self._tasks = []

    def _drain_queue(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

    async def _release_slot(self) -> None:
        if self._slot_acquired:
            self._slot_acquired = False
            await live_limiter.release()

    # --- provider callbacks ---

    async def _on_provider_error(self, exc: Exception) -> None:
        code = getattr(exc, "code", "PROVIDER_DISCONNECTED")
        await self.fail(code, "Сбой STT-провайдера")

    async def _on_result(self, r: RealtimeProviderResult) -> None:
        ch = self._channel_by_index.get(r.channel_index)
        if ch is None or self.state.start_server_ms is None:
            return
        start_ms = self.state.start_server_ms + round(max(0.0, r.start) * 1000)
        end_ms = self.state.start_server_ms + round(max(0.0, r.start + r.duration) * 1000)
        text = r.transcript
        # TODO(stage9): этот per-channel сегмент несёт channel_label/track_id/source_kind
        # (изолированный канал = реальный per-source pipeline), НО НЕ имеет диаризованного
        # speaker_label (сегменты индексируются по каналу, не по спикеру). Когда канал начнёт
        # давать speaker_label, можно строить source_attribution через
        # build_segment_source_attribution_dict(speaker_label=..., channel_label=ch.label,
        #   audio_source_id=ch.track_id, source_is_isolated=True,
        #   attribution_source="multi_source_segment", source_kind="multi_channel",
        #   attribution_confidence=r.confidence) и звать session.observe_speaker_audio_attribution.
        # ch.side — это side_hint (НЕ сторона переговоров) — НЕ использовать как side.
        seg = LiveMultiChannelSegment(
            segment_id=_seg_id(self.session_id, r.channel_index, start_ms, end_ms, text),
            session_id=self.session_id, channel_index=r.channel_index,
            channels_count=r.channels_count, track_id=ch.track_id, channel_label=ch.label,
            side=ch.side, transcript=text, confidence=r.confidence,
            provider_start=r.start, provider_end=r.start + r.duration,
            start_server_ms=start_ms, end_server_ms=end_ms,
            is_final=r.is_final, speech_final=r.speech_final, words=r.words,
        )
        if not r.is_final:
            if text.strip():
                self.state.latest_interim_by_channel[r.channel_index] = seg
                await self._maybe_broadcast_result(seg)
            else:
                self.state.latest_interim_by_channel.pop(r.channel_index, None)
            return
        if not text.strip():
            return
        if any(s.segment_id == seg.segment_id for s in self.state.final_segments):
            return
        self.state.final_segments.append(seg)
        self.state.latest_interim_by_channel.pop(r.channel_index, None)
        await self._broadcast_result(seg)
        # Этап 9.7: уведомить reconciliation о новом final (только final; сбой не критичен)
        if self._on_final_segment is not None:
            try:
                await self._on_final_segment(seg)
            except Exception:
                logger.debug("mc-live on_final_segment callback error")

    async def _maybe_broadcast_result(self, seg: LiveMultiChannelSegment) -> None:
        now = time.monotonic()
        if (now - self._last_interim_broadcast) * 1000 < self._settings.multi_channel_live_interim_broadcast_ms:
            return
        self._last_interim_broadcast = now
        await self._broadcast_result(seg)

    async def _broadcast_result(self, seg: LiveMultiChannelSegment) -> None:
        await self._broadcast({"type": "multi_channel_live_result", "result": _segment_dict(seg)})

    async def _broadcast_state(self) -> None:
        # критические/терминальные переходы — всегда сразу; streaming-апдейты троттлятся
        critical = self.state.status in ("failed", "stopped", "stopping", "degraded") \
            or self.state.error_code is not None
        now = time.monotonic()
        if not critical:
            min_ms = self._settings.multi_channel_live_state_broadcast_ms
            if (now - self._last_state_broadcast) * 1000 < min_ms:
                return
        self._last_state_broadcast = now
        await self._broadcast({"type": "multi_channel_live_state", **self.state_payload()})

    # --- payloads (без PCM/raw/key) ---

    def state_payload(self) -> dict:
        return {
            "session_id": self.session_id, "meeting_id": self.state.meeting_id,
            "status": self.state.status, "provider": self.state.provider,
            "model": self.state.model, "language": self.state.language,
            "channel_count": len(self._channels),
            "channels": [_channel_dict(c) for c in self._channels],
            "started_at": self.state.started_at.isoformat() if self.state.started_at else None,
            "start_frame_index": self.state.start_frame_index,
            "start_server_ms": self.state.start_server_ms,
            "chunks_sent": self.state.chunks_sent, "frames_sent": self.state.frames_sent,
            "bytes_sent": self.state.bytes_sent,
            "provider_queue_depth": self.state.provider_queue_depth,
            "provider_request_id": self.state.provider_request_id,
            "silence_ratio_by_channel": self.state.silence_ratio_by_channel,
            "error_code": self.state.error_code, "error_message": self.state.error_message,
        }

    def snapshot_payload(self) -> dict:
        return {
            "type": "multi_channel_live_snapshot",
            "state": self.state_payload(),
            "final_segments": [_segment_dict(s) for s in self.state.final_segments],
            "latest_interim_by_channel": {
                str(k): _segment_dict(v) for k, v in self.state.latest_interim_by_channel.items()
            },
        }


def _channel_dict(c: RealtimeMuxChannel) -> dict:
    return {
        "channel_index": c.channel_index, "track_id": c.track_id,
        "connection_id": c.connection_id, "generation": c.generation,
        "source_kind": c.source_kind, "label": c.label, "side": c.side,
    }


def _word_dict(w) -> dict:
    return {"text": w.text, "start": w.start, "end": w.end,
            "confidence": w.confidence, "punctuated_word": w.punctuated_word}


def _segment_dict(s: LiveMultiChannelSegment) -> dict:
    return {
        "segment_id": s.segment_id, "session_id": s.session_id,
        "channel_index": s.channel_index, "channels_count": s.channels_count,
        "track_id": s.track_id, "channel_label": s.channel_label, "side": s.side,
        "transcript": s.transcript, "confidence": s.confidence,
        "provider_start": s.provider_start, "provider_end": s.provider_end,
        "start_server_ms": s.start_server_ms, "end_server_ms": s.end_server_ms,
        "is_final": s.is_final, "speech_final": s.speech_final,
        "words": [_word_dict(w) for w in s.words],
    }
