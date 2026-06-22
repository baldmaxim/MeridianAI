"""MeetingRoom: live-сессия привязана к meeting_id, а не к user_id (Этап 2).

Архитектура (наименее рискованный вариант): SessionManager остаётся STT/LLM-движком,
а MeetingRoom надстраивается поверх него — реестр соединений (multi-device),
активный источник аудио, broadcast событий всем подключённым устройствам.
Вывод движка (`set_ws_send`) перенаправлен в `MeetingRoom.broadcast`.

Registry — in-memory (Redis пока не нужен). Структура изолирует registry и broadcast,
чтобы позже заменить на Redis/pubsub:
  - RoomRegistry — точка подмены на distributed-реестр;
  - MeetingRoom.broadcast — точка подмены на pub/sub fan-out между процессами.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import select, update

from ..config import get_settings
from ..database import async_session
from .observer_diarization import ObserverDiarization
from .secondary_audio_shadow import SecondaryAudioShadow
from .multi_source_ingest import MultiSourceIngest, ROLE_PRIMARY, ROLE_SECONDARY
from .device_clock import ClockSyncReport, classify_quality
from .speaker_roles import to_public_side
from .realtime_multi_channel_mux import RealtimeMuxChannel
from .multi_channel_live_session import MultiChannelLiveSession
from .deepgram_realtime_multichannel import DeepgramRealtimeMultichannelProvider
from .multi_channel_reconciliation import reconcile_segments, state_to_dict
from .committed_transcript_snapshot import (
    build_primary_segments_for_reconciliation,
    build_channel_segments_for_reconciliation,
)
from .transcription_authority_controller import TranscriptionAuthorityController
from ..models.meeting import (
    MeetingSession,
    TranscriptSegmentRecord,
    MeetingDocumentRecord,
)
from ..core.context.document_loader import MeetingDocument
from .session_manager import SessionManager
from .meeting_setup import (
    load_user_settings,
    load_default_role,
    load_role_by_id,
    apply_custom_hint_settings,
)
from .api_keys import load_api_keys
from .local_storage import save_meeting_to_local
from .meeting_audio_recorder import SessionAudioRecorder, pcm_to_wav
from .access import can_record_meeting, current_user_meeting_role
from .document_context import build_meeting_doc_context
from .knowledge_context import build_meeting_knowledge_context
from .previous_meeting_context import get_previous_meeting_context_for_prompt
from .rag_context import build_meeting_rag_context
from .letters_context import build_meeting_letters_context
from .ai_settings import snapshot_for_meeting

logger = logging.getLogger("meridian.room")

VALID_DEVICE_ROLES = ("desktop", "phone", "viewer", "participant", "observer", "secondary")
# роли, которым в Этапе 2 разрешено быть источником аудио (observer/secondary — никогда)
AUDIO_CAPABLE_ROLES = ("desktop", "phone")


class MeetingConnection:
    """Одно WebSocket-соединение устройства/пользователя к встрече."""

    def __init__(self, meeting_id: int, user_id: int, device_role: str, send_json,
                 can_record: bool = False):
        self.connection_id: str = uuid.uuid4().hex[:16]
        self.meeting_id: int = meeting_id
        self.user_id: int = user_id
        self.device_role: str = device_role
        self.can_record: bool = can_record
        # Этап 3: источником аудио может быть только desktop/phone И с правом записи
        # (can_record_meeting). viewer — никогда; phone/desktop с view-доступом — нет.
        self.can_send_audio: bool = device_role in AUDIO_CAPABLE_ROLES and can_record
        self.is_active_audio_source: bool = False
        self.send_json = send_json  # async def(data: dict) -> None
        self.connected_at: datetime = datetime.utcnow()
        self.last_seen_at: datetime = self.connected_at
        # Этап 9.1: device clock sync. None пока устройство не синхронизировалось.
        self.clock: ClockSyncReport | None = None

    def to_server_ms(self, client_ts_ms: int | float) -> float:
        """Перевести клиентский epoch-ms в server timeline по offset устройства.

        Graceful: если синхронизации ещё не было — возвращаем как есть.
        """
        try:
            base = float(client_ts_ms)
        except (TypeError, ValueError):
            return float(client_ts_ms) if isinstance(client_ts_ms, (int, float)) else 0.0
        if self.clock is None:
            return base
        return base + self.clock.offset_ms

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "user_id": self.user_id,
            "device_role": self.device_role,
            "can_send_audio": self.can_send_audio,
            "is_active_audio_source": self.is_active_audio_source,
            "connected_at": self.connected_at.isoformat(),
            "clock": {
                "offset_ms": self.clock.offset_ms,
                "rtt_ms": self.clock.rtt_ms,
                "quality": self.clock.quality,
                "samples_count": self.clock.samples_count,
            } if self.clock else None,
        }


class MeetingRoom:
    """Live-комната встречи: реестр соединений + единый STT/LLM-движок (SessionManager)."""

    def __init__(self, meeting_id: int, owner_user_id: int | None, status: str | None):
        self.meeting_id = meeting_id
        self.owner_user_id = owner_user_id
        self.status = status
        self.connections: dict[str, MeetingConnection] = {}
        self.active_audio_source: str | None = None  # connection_id
        # Задача 2b: кто и с какого момента ведёт запись (для таймера/шапки наблюдателей)
        self.recording_started_at_ms: int | None = None
        self.active_audio_user_label: str | None = None
        self._user_label_cache: dict[int, str] = {}
        # Задача 3: серверная запись живого аудио активного источника → temp → S3 при финализации
        self.audio_recorder = SessionAudioRecorder(meeting_id)
        self.settings: dict = {}
        self.api_keys: dict = {}
        self.closed = False
        # STT/LLM-движок этой встречи; вывод → broadcast
        self.session = SessionManager(owner_user_id or 0)
        self.session.db_session_id = meeting_id
        # Conversation Tree (дерево общения)
        self._tree_enabled = True
        self._tree_version = 0
        # Этап 9: observer-диаризация (метрики уровня звука вторых устройств)
        self.observer = ObserverDiarization(get_settings())
        # Этап 9.2: secondary audio shadow (аудио-чанки вторых устройств БЕЗ STT)
        self.shadow = SecondaryAudioShadow(get_settings())
        # Этап 9.3: единый ingest-слой (общая server timeline для всех источников)
        self.ingest = MultiSourceIngest(get_settings())
        self._last_ingest_emit_ms: int = 0
        # Этап 9.6: realtime multi-channel live STT shadow (одна сессия на встречу)
        self.multi_channel_live: MultiChannelLiveSession | None = None
        # Этап 9.7: channel-aware reconciliation (in-memory evidence; ничего не сохраняется)
        self.multi_channel_reconciliation = None
        self._reconciliation_revision: int = 0
        self._reconciliation_task: asyncio.Task | None = None
        self._reconciliation_pending: bool = False
        # Этап 9.8: контроллер авторитетного источника транскрипта (cutover).
        # Single STT остаётся всегда-включённым hot standby; promote только ручной.
        self.cutover = TranscriptionAuthorityController(
            meeting_id=meeting_id, owner_user_id=owner_user_id,
            get_session=lambda: self.session,
            get_live=lambda: self.multi_channel_live,
            get_reconciliation_summary=self._reconciliation_summary_for_quality,
            get_channel_clock_quality=self._channel_clock_quality_for_quality,
            broadcast=self.broadcast,
        )
        # авторитетный транскрипт в контекст подсказок (None → single, поведение без изменений)
        self.session.set_authoritative_transcript_provider(self.cutover.live_authoritative_text)

    # --- создание/конфигурация ---

    @classmethod
    async def create(cls, meeting_id: int) -> "MeetingRoom":
        """Загрузить встречу, восстановить контекст/документы и сконфигурировать движок."""
        async with async_session() as db:
            meeting = (
                await db.execute(
                    select(MeetingSession).where(MeetingSession.id == meeting_id)
                )
            ).scalar_one_or_none()
            owner = None
            status = None
            if meeting:
                owner = meeting.created_by_user_id or meeting.user_id
                status = meeting.status
            room = cls(meeting_id, owner, status)

            if meeting:
                s = room.session
                s.document_loader.meeting_topic = meeting.meeting_topic or ""
                s.document_loader.meeting_notes = meeting.meeting_notes or ""
                s.negotiation_type = meeting.negotiation_type or "sale"
                s.meeting_role = meeting.meeting_role or ""
                s.opponent_weaknesses = meeting.opponent_weaknesses or ""
                s.meeting_title = meeting.title or ""
                if not s.document_loader.documents:
                    docs = (
                        await db.execute(
                            select(MeetingDocumentRecord).where(
                                MeetingDocumentRecord.session_id == meeting_id
                            )
                        )
                    ).scalars().all()
                    for d in docs:
                        # Bug B: S3-документы (новый flow) не имеют inline content —
                        # их текст подаётся через DocumentChunk-провайдер
                        # (build_meeting_doc_context). В legacy in-memory loader кладём
                        # только документы с реальным inline-текстом, чтобы не падать
                        # на len(None) при сборке промпта.
                        if not (d.content and d.content.strip()):
                            continue
                        s.document_loader.documents.append(
                            MeetingDocument(
                                filename=d.filename,
                                content=d.content,
                                doc_type=d.doc_type,
                                loaded_at=d.created_at,
                                page_count=d.page_count,
                            )
                        )

                # Conversation Tree: загрузить persisted-роли спикеров (source of truth)
                try:
                    from .speaker_roles import get_roles_map
                    s.speaker_roles = await get_roles_map(db, meeting_id)
                except Exception as e:
                    logger.warning(f"[room {meeting_id}] load speaker roles failed: {e}")

                # Этап 8: загрузить segment-level коррекции диаризации в live-кэш
                try:
                    from .speaker_corrections import get_segment_corrections_cache
                    s.set_speaker_segment_corrections(await get_segment_corrections_cache(db, meeting_id))
                except Exception as e:
                    logger.warning(f"[room {meeting_id}] load speaker corrections failed: {e}")

        # конфигурация движка по настройкам владельца встречи
        room.settings = await load_user_settings(owner)
        room.api_keys = await load_api_keys()

        # Этап 9: заморозить AI-настройки встречи (snapshot) и применить модель/STT/тогглы
        ai_resolved: dict = {}
        try:
            async with async_session() as db:
                ai_resolved = await snapshot_for_meeting(db, meeting_id)
                await db.commit()
        except Exception as e:
            logger.warning(f"[room {meeting_id}] AI settings snapshot failed: {e}")
        if ai_resolved.get("live_suggestion_model"):
            room.settings["llm_model"] = ai_resolved["live_suggestion_model"]
        if ai_resolved.get("stt_provider"):
            room.settings["stt_provider"] = ai_resolved["stt_provider"]

        openrouter_key = room.api_keys.get("openrouter", "")
        if openrouter_key:
            room.session.configure_llm(
                api_key=openrouter_key,
                model=room.settings["llm_model"],
                temperature=room.settings["temperature"],
            )
        room.session.set_ai_settings(ai_resolved or None)
        role_data = await load_default_role(owner)
        if role_data:
            room.session.set_role(role_data)
        apply_custom_hint_settings(room.session, room.settings)

        # ВЕСЬ вывод движка (транскрипт/подсказки/статус) уходит в broadcast
        room.session.set_ws_send(room.broadcast)
        # Этап 4: документы встречи в контекст LLM-подсказок
        room.session.set_doc_context_provider(build_meeting_doc_context)
        # Этап 7: утверждённая база знаний в контекст LLM-подсказок
        room.session.set_knowledge_provider(build_meeting_knowledge_context)
        # Этап 8: итоги выбранных прошлых встреч в контекст LLM-подсказок
        room.session.set_previous_meetings_provider(get_previous_meeting_context_for_prompt)
        # Этап 5 (RAG): фрагменты подключённых RAG-папок в контекст LLM-подсказок
        room.session.set_rag_context_provider(build_meeting_rag_context)
        # Письма PayHub (внешний RAG): блок переписки в контекст LLM-подсказок
        room.session.set_letters_context_provider(build_meeting_letters_context)
        # Conversation Tree: обновление дерева общения по committed-сегментам
        room._tree_enabled = bool(ai_resolved.get("conversation_tree_enabled", True))
        room.session.set_committed_hook(room._on_committed_segment)
        # Этап 9.8: загрузить эпохи + recovery (открытая multi-эпоха после рестарта → fallback)
        try:
            await room.cutover.load()
            await room.cutover.recover()
        except Exception as e:
            logger.warning(f"[room {meeting_id}] cutover load/recover failed: {e}")
        logger.info(f"[room {meeting_id}] created (owner={owner}, status={status})")
        return room

    # --- broadcast / адресная отправка ---

    async def broadcast(self, data: dict, roles: list[str] | None = None,
                        exclude: str | None = None) -> None:
        """Разослать событие всем соединениям (опц. фильтр по ролям / исключение).

        Точка подмены под Redis pub/sub: здесь fan-out по локальным соединениям;
        в distributed-варианте сюда же прилетают события из других процессов.
        """
        for conn in list(self.connections.values()):
            if exclude and conn.connection_id == exclude:
                continue
            if roles and conn.device_role not in roles:
                continue
            try:
                await conn.send_json(data)
            except Exception:
                pass  # «мёртвое» соединение — снимется в своём finally/disconnect

    async def send_to_connection(self, connection_id: str, data: dict) -> None:
        conn = self.connections.get(connection_id)
        if conn:
            try:
                await conn.send_json(data)
            except Exception:
                pass

    # --- соединения ---

    async def add_connection(self, conn: MeetingConnection) -> None:
        self.connections[conn.connection_id] = conn
        # Этап 9: observer-устройство регистрируется в буфере метрик (raw audio не шлёт)
        if conn.device_role == "observer":
            self.observer.register_device(conn.connection_id, conn.user_id, conn.device_role)
        # Этап 9.2: secondary-устройство — idle-трек shadow (буферизация после enable)
        elif conn.device_role == "secondary":
            self.shadow.register_track(conn.connection_id, conn.user_id)
        # подключившемуся — room_joined + восстановленный контекст + статус записи
        await conn.send_json({
            "type": "room_joined",
            "meeting_id": self.meeting_id,
            "connection_id": conn.connection_id,
            "device_role": conn.device_role,
            "can_send_audio": conn.can_send_audio,
            "active_audio_source": self.active_audio_source,
        })
        await conn.send_json({
            "type": "meeting_context",
            "title": self.session.meeting_title,
            "topic": self.session.document_loader.meeting_topic,
            "notes": self.session.document_loader.meeting_notes,
            "negotiation_type": self.session.negotiation_type,
            "meeting_role": self.session.meeting_role,
            "opponent_weaknesses": self.session.opponent_weaknesses,
        })
        await conn.send_json(self._recording_status_payload(self.session.is_listening))
        # текущие роли спикеров (восстановление после refresh)
        if self.session.speaker_roles:
            await conn.send_json({
                "type": "speaker_roles_updated",
                "roles": self.session.speaker_roles,
            })
        # Этап 9.6: на join — текущее состояние live multi-channel (+ snapshot если есть)
        if self.multi_channel_live:
            await conn.send_json(self.multi_channel_live.snapshot_payload())
        else:
            await conn.send_json({
                "type": "multi_channel_live_state", "session_id": None, "status": "idle",
                "channels": [], "channel_count": 0,
            })
        # Этап 9.7: на join — текущий reconciliation snapshot (или null)
        await conn.send_json(self._reconciliation_snapshot_event())
        # Этап 9.8: на join — состояние авторитетного источника транскрипта (cutover)
        await conn.send_json({"type": "transcription_authority_state", **self.cutover.state_dict()})
        # остальным — device_joined
        await self.broadcast(
            {
                "type": "device_joined",
                "meeting_id": self.meeting_id,
                "connection_id": conn.connection_id,
                "device_role": conn.device_role,
            },
            exclude=conn.connection_id,
        )

    async def remove_connection(self, connection_id: str) -> None:
        conn = self.connections.pop(connection_id, None)
        if not conn:
            return
        self.observer.remove_device(connection_id)  # Этап 9: чистим метрики observer
        self.ingest.remove_track(connection_id)  # Этап 9.3: чистим ingest-трек устройства
        if conn.device_role == "secondary":
            self.shadow.remove_track(connection_id)  # Этап 9.2: чистим shadow-трек
            await self._broadcast_shadow_summary()
        if self.active_audio_source == connection_id:
            # источник аудио отключился — НЕ финализируем встречу, только чистим источник
            was_phone = conn.device_role == "phone"
            self.active_audio_source = None
            self._reset_recording_meta()
            if self.session.is_listening:
                await self.session.stop_listening()
            await self.broadcast({
                "type": "audio_source_disconnected",
                "meeting_id": self.meeting_id,
            })
            if was_phone:
                await self.broadcast({
                    "type": "phone_recording_stopped",
                    "connection_id": connection_id,
                })
        await self.broadcast({
            "type": "device_left",
            "meeting_id": self.meeting_id,
            "connection_id": connection_id,
        })
        # комната опустела — сохранить сегменты (без закрытия встречи), чтобы не потерять
        if not self.connections and not self.closed:
            await self._persist_segments(close=False)

    # --- активный источник аудио ---

    def set_active_audio_source(self, connection_id: str) -> None:
        self.active_audio_source = connection_id
        for c in self.connections.values():
            c.is_active_audio_source = c.connection_id == connection_id

    def clear_active_audio_source(self, connection_id: str) -> None:
        if self.active_audio_source == connection_id:
            self.active_audio_source = None
        conn = self.connections.get(connection_id)
        if conn:
            conn.is_active_audio_source = False

    def _reset_recording_meta(self) -> None:
        self.recording_started_at_ms = None
        self.active_audio_user_label = None

    async def _user_label(self, user_id: int | None) -> str | None:
        """Ярлык аккаунта для UI (display_name или локальная часть email). В логи не пишем."""
        if user_id is None:
            return None
        if user_id in self._user_label_cache:
            return self._user_label_cache[user_id]
        label: str | None = None
        try:
            from ..models.user import User
            async with async_session() as db:
                u = await db.get(User, user_id)
                if u:
                    label = u.display_name or (u.email.split("@", 1)[0] if u.email else None)
        except Exception:
            label = None
        if label:
            self._user_label_cache[user_id] = label
        return label

    def _recording_status_payload(self, recording: bool) -> dict:
        """Единый формат recording_status (+ кто пишет и с какого момента — Задача 2b)."""
        return {
            "type": "recording_status",
            "recording": recording,
            "active_audio_source": self.active_audio_source if recording else None,
            "active_audio_user_label": self.active_audio_user_label if recording else None,
            "recording_started_at_ms": self.recording_started_at_ms if recording else None,
        }

    async def handle_audio_frame(self, connection_id: str, data: bytes) -> None:
        """Бинарный аудио-фрейм.

        secondary-устройство → shadow-буфер (БЕЗ STT, не меняет active_audio_source);
        иначе принимается ТОЛЬКО от активного источника и идёт в STT.
        """
        conn = self.connections.get(connection_id)
        if conn is not None and conn.device_role == "secondary":
            await self._handle_shadow_frame(conn, data)
            return
        if connection_id != self.active_audio_source:
            return
        if self.session.is_listening and self.session.audio_queue:
            self.session.touch()
            # STT-поток БЕЗ изменений: ровно те же байты уходят в очередь STT.
            await self.session.audio_queue.put((datetime.now(), data))
            # Задача 3: тот же PCM активного источника пишем на диск для архива (не влияет на STT).
            self.audio_recorder.append(data)
            # Этап 9.3: tap в ingest-слой (параллельно, не влияет на STT). Никогда не ломаем STT.
            await self._tap_primary_ingest(connection_id, data)

    async def _tap_primary_ingest(self, connection_id: str, data: bytes) -> None:
        """Этап 9.3: копия primary-PCM в ingest-слой. Primary STT-поток не затрагивается.

        primary-кадр не несёт per-frame client_ts, поэтому время ЗАХВАТА на server timeline
        оцениваем как arrival − rtt/2 (по device clock sync соединения). Тогда primary и
        secondary лежат на ОДНОЙ шкале: secondary кладёт client_ts(=время отправки)+offset,
        primary — arrival−rtt/2 (≈ время отправки). Оценка приблизительная (остаточный сдвиг
        в пределах клиентской буферизации, ~одинаковой у обоих ~100мс), но согласованная.
        """
        if not self.ingest.enabled:
            return
        try:
            conn = self.connections.get(connection_id)
            now_ms = int(time.time() * 1000)
            half_rtt = (conn.clock.rtt_ms / 2.0) if (conn and conn.clock) else 0.0
            server_ts_ms = int(now_ms - half_rtt)
            self.ingest.ingest(
                connection_id, ROLE_PRIMARY,
                server_ts_ms=server_ts_ms, arrival_ms=now_ms, pcm=data,
                sample_rate=16000, channels=1, codec="pcm16",
            )
            await self._maybe_broadcast_ingest(now_ms)
        except Exception:
            pass  # ingest никогда не должен влиять на основной аудиопоток

    async def _handle_shadow_frame(self, conn: "MeetingConnection", frame: bytes) -> None:
        """Этап 9.2: разобрать shadow-кадр и буферизовать; Этап 9.3: подать в ingest-слой.

        Кадры secondary-устройства НЕ идут в STT. Логи без PII/байтов.

        # Secondary audio protocol v1:
        # [uint16 BE header_length][UTF-8 JSON header][PCM16 LE mono payload]
        # Framing is already deployed; changes require protocol_version compatibility.
        """
        try:
            if len(frame) < 2:
                return
            header_len = int.from_bytes(frame[0:2], "big")
            if header_len <= 0 or 2 + header_len > len(frame):
                return
            header = json.loads(bytes(frame[2:2 + header_len]).decode("utf-8"))
            payload = frame[2 + header_len:]
        except Exception:
            return
        if not isinstance(header, dict):
            return
        raw_ts = header.get("client_ts_ms")
        # bool — подкласс int; не считаем true/false валидным timestamp
        client_ts_ms = raw_ts if isinstance(raw_ts, int) and not isinstance(raw_ts, bool) else None
        server_ts_ms = int(conn.to_server_ms(client_ts_ms)) if client_ts_ms is not None \
            else int(time.time() * 1000)
        try:
            seq = int(header.get("seq", 0))
        except (TypeError, ValueError):
            return
        accepted, _reason = self.shadow.add_chunk(
            conn.connection_id,
            seq=seq,
            client_ts_ms=client_ts_ms,
            server_ts_ms=server_ts_ms,
            payload_bytes=len(payload),
            payload=bytes(payload),
            sample_rate=header.get("sample_rate"),
            channels=header.get("channels"),
            codec=header.get("codec"),
            rms=header.get("rms"),
            peak=header.get("peak"),
        )
        # Этап 9.3: тот же secondary PCM подаётся в ingest-слой (общая timeline).
        # Полный PCM хранится ТОЛЬКО здесь (9.2 ring buffer держит лишь метаданные).
        if accepted and self.ingest.enabled:
            t0 = self.shadow.tracks.get(conn.connection_id)
            try:
                self.ingest.ingest(
                    conn.connection_id, ROLE_SECONDARY,
                    server_ts_ms=server_ts_ms, arrival_ms=int(time.time() * 1000),
                    pcm=bytes(payload), seq=seq, client_ts_ms=client_ts_ms,
                    sample_rate=int(header.get("sample_rate") or 16000),
                    channels=int(header.get("channels") or 1),
                    codec=str(header.get("codec") or "pcm16").lower(),
                    side_hint=t0.side_hint if t0 else None,
                )
            except Exception:
                pass

        # периодическая диагностика отправителю + сводка в комнату (без таймера)
        t = self.shadow.tracks.get(conn.connection_id)
        if accepted and t is not None and t.chunks_count % self._shadow_diag_every(t) == 0:
            now_ms = int(time.time() * 1000)
            diag = self.shadow.track_diag(conn.connection_id, now_ms)
            if diag is not None:
                await self.send_to_connection(conn.connection_id,
                                              {"type": "secondary_shadow_diag", **diag})
            await self._broadcast_shadow_summary(now_ms=now_ms)
            await self._maybe_broadcast_ingest(now_ms)

    @staticmethod
    def _shadow_diag_every(t) -> int:
        """Слать диагностику примерно раз в секунду (по длительности чанков)."""
        dur = t.last_duration_ms or 100
        return max(1, int(round(1000 / max(1, dur))))

    async def _broadcast_shadow_summary(self, now_ms: int | None = None) -> None:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        await self.broadcast({
            "type": "secondary_shadow_track",
            "meeting_id": self.meeting_id,
            "tracks": self.shadow.room_summary(now_ms),
        })

    async def _maybe_broadcast_ingest(self, now_ms: int) -> None:
        """Этап 9.3: сводка выравнивания ingest-слоя в комнату (троттлинг ~1с)."""
        if not self.ingest.enabled or now_ms - self._last_ingest_emit_ms < 1000:
            return
        self._last_ingest_emit_ms = now_ms
        await self.broadcast({
            "type": "multi_source_alignment",
            "meeting_id": self.meeting_id,
            **self.ingest.alignment_summary(),
        })

    # --- Этап 9.6: realtime multi-channel live STT shadow ---

    def _live_can_edit(self, connection_id: str) -> bool:
        conn = self.connections.get(connection_id)
        return bool(conn and conn.can_record)

    @staticmethod
    def _live_label(source_kind: str, side: str | None) -> str:
        if source_kind == "primary":
            return "Основной канал"
        if side == "self":
            return "Shadow — Мы"
        if side == "opponent":
            return "Shadow — Не мы"
        return "Shadow — сторона не указана"

    async def _send_live_error(self, connection_id: str, code: str, message: str) -> None:
        await self.send_to_connection(connection_id, {
            "type": "multi_channel_live_state", "session_id": None, "status": "failed",
            "error_code": code, "error_message": message, "channels": [], "channel_count": 0,
        })

    async def _send_live_snapshot(self, connection_id: str) -> None:
        if self.multi_channel_live:
            await self.send_to_connection(connection_id, self.multi_channel_live.snapshot_payload())
        else:
            await self.send_to_connection(connection_id, {
                "type": "multi_channel_live_state", "session_id": None, "status": "idle",
                "channels": [], "channel_count": 0,
            })

    async def _handle_live_start(self, connection_id: str, message: dict) -> None:
        settings = get_settings()
        conn = self.connections.get(connection_id)
        if conn is None or not conn.can_record:
            await self._send_live_error(connection_id, "FORBIDDEN", "Нет права запускать live shadow")
            return
        if not settings.multi_channel_live_enabled:
            await self._send_live_error(connection_id, "FEATURE_DISABLED", "Live multi-channel выключен")
            return
        if settings.multi_channel_live_provider != "deepgram":
            await self._send_live_error(connection_id, "UNSUPPORTED_PROVIDER", "Провайдер не поддерживается")
            return
        if message.get("consent_confirmed") is not True:
            await self._send_live_error(connection_id, "CONSENT_REQUIRED", "Требуется подтверждение согласия")
            return
        dg_key = (self.api_keys or {}).get("deepgram", "")
        if not dg_key:
            await self._send_live_error(connection_id, "PROVIDER_NOT_CONFIGURED", "STT-провайдер не настроен")
            return
        if self.multi_channel_live and self.multi_channel_live.state.status in (
                "buffering", "connecting", "streaming", "degraded"):
            await self.send_to_connection(connection_id, {
                "type": "multi_channel_live_state", **self.multi_channel_live.state_payload()})
            return

        track_ids = message.get("track_ids")
        if not isinstance(track_ids, list) or any(not isinstance(t, str) or not t for t in track_ids):
            await self._send_live_error(connection_id, "INVALID_REQUEST", "Некорректный список каналов")
            return
        if len(set(track_ids)) != len(track_ids):
            await self._send_live_error(connection_id, "INVALID_REQUEST", "Каналы должны быть уникальны")
            return
        if not (settings.multi_channel_live_min_channels <= len(track_ids)
                <= settings.multi_channel_live_max_channels):
            await self._send_live_error(connection_id, "INVALID_CHANNEL_COUNT", "Недопустимое число каналов")
            return

        target_sr = settings.secondary_audio_shadow_target_sample_rate or 16000
        overrides = message.get("channel_side_overrides") or {}
        channels = []
        for idx, tid in enumerate(track_ids):
            t = self.ingest.tracks.get(tid)
            if t is None:
                await self._send_live_error(connection_id, "TRACK_NOT_FOUND", f"Канал не найден: {tid}")
                return
            # mux предполагает canonical mono PCM16 на target sample_rate; иначе кадр канала
            # не совпал бы по размеру и канал молчал бы — отклоняем явно.
            if t.codec != "pcm16" or t.channels != 1 or t.sample_rate != target_sr:
                await self._send_live_error(connection_id, "CHANNEL_FORMAT_MISMATCH",
                                            f"Канал {tid} не в формате mono PCM16 {target_sr} Гц")
                return
            if tid in overrides:
                side = to_public_side(overrides.get(tid))
            else:
                side = t.side_hint
            channels.append(RealtimeMuxChannel(
                channel_index=idx, track_id=tid, connection_id=tid, generation=0,
                source_kind=t.role, label=self._live_label(t.role, side), side=side,
            ))

        kinds = {c.source_kind for c in channels}
        if "primary" not in kinds:
            await self._send_live_error(connection_id, "NO_PRIMARY", "Нужен primary-канал")
            return
        if "secondary" not in kinds:
            await self._send_live_error(connection_id, "NO_SECONDARY", "Нужен secondary-канал")
            return

        lo, hi = self.ingest.get_common_range(track_ids)
        if lo is None or hi is None:
            await self._send_live_error(connection_id, "ALIGNMENT_NOT_READY", "Каналы ещё не выровнены")
            return

        # clock quality для secondary должна быть приемлемой
        for c in channels:
            if c.source_kind != "secondary":
                continue
            sc = self.connections.get(c.connection_id)
            q = sc.clock.quality if (sc and sc.clock) else None
            if q in (None, "poor"):
                await self._send_live_error(connection_id, "CLOCK_QUALITY",
                                            "Качество синхронизации secondary-канала недостаточно")
                return

        provider = DeepgramRealtimeMultichannelProvider(
            api_key=dg_key, base_url=settings.deepgram_streaming_url,
            keepalive_seconds=settings.multi_channel_live_keepalive_seconds,
            close_timeout_seconds=settings.multi_channel_live_close_timeout_seconds,
        )
        # новая live-сессия → сбросить reconciliation предыдущей
        await self._clear_multi_channel_reconciliation()
        session = MultiChannelLiveSession(
            meeting_id=self.meeting_id, owner_user_id=conn.user_id, ingest=self.ingest,
            broadcast=self.broadcast, provider=provider, channels=tuple(channels), settings=settings,
            on_final_segment=self._on_live_final_segment,
            on_terminal=self._on_live_terminal,
        )
        self.multi_channel_live = session
        await session.start()

    async def stop_multi_channel_live(self) -> None:
        if self.multi_channel_live:
            try:
                await self.multi_channel_live.stop()
            except Exception:
                pass

    # --- Этап 9.7: channel-aware reconciliation ---

    async def _on_live_final_segment(self, segment) -> None:
        # Этап 9.8: promoted на multi → сохранить normalized final сегмент (без raw/PCM)
        if segment is not None:
            try:
                await self.cutover.persist_live_final(segment)
            except Exception:
                logger.debug("[room %s] persist live final failed", self.meeting_id)
        await self._schedule_multi_channel_reconciliation(reason="live_final")

    @staticmethod
    def _live_is_active(live) -> bool:
        return live is not None and live.state.status in (
            "buffering", "connecting", "streaming", "degraded")

    # --- Этап 9.8: аксессоры качества + терминальный колбэк для cutover ---

    def _reconciliation_summary_for_quality(self):
        """(matched, total_primary) из текущего reconciliation для quality gate, или None."""
        st = self.multi_channel_reconciliation
        summary = getattr(st, "summary", None) if st is not None else None
        if summary is None:
            return None
        matched = getattr(summary, "matched", 0)
        total = matched + getattr(summary, "primary_only", 0) + getattr(summary, "ambiguous", 0)
        return (matched, total)

    def _channel_clock_quality_for_quality(self) -> dict:
        live = self.multi_channel_live
        if not live:
            return {}
        out = {}
        for c in live.state.channels:
            conn = self.connections.get(c.connection_id)
            out[c.channel_index] = (conn.clock.quality if (conn and conn.clock) else None)
        return out

    async def _on_live_terminal(self) -> None:
        """Live promoted-сессия завершилась (stop/fail) → авто-fallback на single STT."""
        try:
            await self.cutover.on_live_failure()
        except Exception:
            logger.debug("[room %s] cutover on_live_failure error", self.meeting_id)

    async def _handle_transcription_promote(self, connection_id: str, message: dict) -> None:
        """Этап 9.8: РУЧНОЕ продвижение встречи на авторитетный multi-channel transcript."""
        conn = self.connections.get(connection_id)
        if not self._live_can_edit(connection_id):
            await self.send_to_connection(connection_id, {
                "type": "transcription_authority_error",
                "code": "FORBIDDEN", "message": "Нет права управлять источником транскрипта"})
            return
        result = await self.cutover.promote(
            by_user_id=conn.user_id if conn else None,
            reason="manual_promote", force=bool(message.get("force")))
        if not result.get("ok"):
            await self.send_to_connection(connection_id, {
                "type": "transcription_authority_error",
                "code": result.get("code"), "message": result.get("message"),
                "quality": result.get("quality"), "state": result.get("state")})

    async def _handle_transcription_fallback(self, connection_id: str, message: dict) -> None:
        """Этап 9.8: РУЧНОЙ откат на single STT."""
        conn = self.connections.get(connection_id)
        if not self._live_can_edit(connection_id):
            await self.send_to_connection(connection_id, {
                "type": "transcription_authority_error",
                "code": "FORBIDDEN", "message": "Нет права управлять источником транскрипта"})
            return
        result = await self.cutover.fallback(
            by_user_id=conn.user_id if conn else None, reason="manual_fallback", automatic=False)
        if not result.get("ok"):
            await self.send_to_connection(connection_id, {
                "type": "transcription_authority_error",
                "code": result.get("code"), "message": result.get("message"),
                "state": result.get("state")})

    async def _schedule_multi_channel_reconciliation(self, *, reason: str,
                                                     immediate: bool = False) -> None:
        settings = get_settings()
        # рефрешим только при НЕтерминальной live-сессии (после stop/fail — не регенерируем)
        if not settings.multi_channel_reconciliation_enabled \
                or not self._live_is_active(self.multi_channel_live):
            return
        if self._reconciliation_task and not self._reconciliation_task.done():
            self._reconciliation_pending = True
            return
        self._reconciliation_task = asyncio.create_task(
            self._reconciliation_runner(reason=reason, immediate=immediate))

    async def _reconciliation_runner(self, *, reason: str, immediate: bool) -> None:
        settings = get_settings()
        delay = settings.multi_channel_reconciliation_refresh_ms / 1000.0
        try:
            if not immediate:
                await asyncio.sleep(delay)
            while True:
                self._reconciliation_pending = False
                await self._refresh_multi_channel_reconciliation(reason=reason)
                if not self._reconciliation_pending:
                    break
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("[room %s] reconciliation runner error", self.meeting_id)
        finally:
            self._reconciliation_task = None

    async def _refresh_multi_channel_reconciliation(self, *, reason: str) -> None:
        settings = get_settings()
        live = self.multi_channel_live
        if not self._live_is_active(live):
            return
        # read-only снимки (без await между ними — атомарно к session/live)
        primary = build_primary_segments_for_reconciliation(
            session=self.session, limit=settings.multi_channel_reconciliation_max_primary_segments)
        channel = build_channel_segments_for_reconciliation(
            live_session=live, limit=settings.multi_channel_reconciliation_max_candidate_segments)
        ratios = list(getattr(live.state, "silence_ratio_by_channel", []) or [])
        silence = {i: ratios[i] for i in range(len(ratios))}
        clock = {}
        for c in live.state.channels:
            conn = self.connections.get(c.connection_id)
            clock[c.channel_index] = (conn.clock.quality if (conn and conn.clock) else None)
        self._reconciliation_revision += 1
        state = reconcile_segments(
            meeting_id=self.meeting_id, session_id=live.session_id,
            primary_segments=primary, channel_segments=channel,
            max_time_delta_ms=settings.multi_channel_reconciliation_max_time_delta_ms,
            min_pair_score=settings.multi_channel_reconciliation_min_pair_score,
            match_score=settings.multi_channel_reconciliation_match_score,
            suggest_score=settings.multi_channel_reconciliation_suggest_score,
            ambiguity_delta=settings.multi_channel_reconciliation_ambiguity_delta,
            max_entries=settings.multi_channel_reconciliation_max_entries,
            channel_silence_ratios=silence, channel_clock_quality=clock,
            revision=self._reconciliation_revision,
        )
        self.multi_channel_reconciliation = state
        await self.broadcast({
            "type": "multi_channel_reconciliation_state",
            "state": state_to_dict(state, max_text_chars=settings.multi_channel_reconciliation_max_text_chars),
        })

    def _reconciliation_snapshot_event(self) -> dict:
        settings = get_settings()
        if self.multi_channel_reconciliation is None:
            return {"type": "multi_channel_reconciliation_snapshot", "state": None}
        return {
            "type": "multi_channel_reconciliation_snapshot",
            "state": state_to_dict(self.multi_channel_reconciliation,
                                   max_text_chars=settings.multi_channel_reconciliation_max_text_chars),
        }

    async def _send_reconciliation_snapshot(self, connection_id: str) -> None:
        await self.send_to_connection(connection_id, self._reconciliation_snapshot_event())

    async def _clear_multi_channel_reconciliation(self) -> None:
        if self._reconciliation_task and not self._reconciliation_task.done():
            self._reconciliation_task.cancel()
            try:
                await self._reconciliation_task
            except (asyncio.CancelledError, Exception):
                pass
        self._reconciliation_task = None
        self._reconciliation_pending = False
        self.multi_channel_reconciliation = None

    async def start_audio(self, connection_id: str) -> None:
        conn = self.connections.get(connection_id)
        if not conn:
            return
        if not conn.can_send_audio:
            # есть доступ к просмотру, но нет права записи (или роль viewer)
            await conn.send_json({
                "type": "record_permission_denied",
                "message": "У вас есть доступ к просмотру встречи, но нет права запускать запись.",
            })
            return
        if self.active_audio_source and self.active_audio_source != connection_id:
            await conn.send_json({
                "type": "audio_source_busy",
                "active_audio_source": self.active_audio_source,
            })
            return
        self.set_active_audio_source(connection_id)
        self.active_audio_user_label = await self._user_label(conn.user_id)
        if not self.session.is_listening:
            self.recording_started_at_ms = int(time.time() * 1000)
            await self.session.start_listening(
                stt_provider=self.settings.get("stt_provider", "deepgram"),
                api_keys=self.api_keys,
                diarization=self.settings.get("diarization", True),
            )
        await self.broadcast(self._recording_status_payload(True))
        if conn.device_role == "phone":
            await self.broadcast({
                "type": "phone_recording_started",
                "connection_id": connection_id,
            })

    async def stop_audio(self, connection_id: str) -> None:
        # останавливать запись может только активный источник
        if self.active_audio_source != connection_id:
            return
        conn = self.connections.get(connection_id)
        was_phone = bool(conn and conn.device_role == "phone")
        if self.session.is_listening:
            await self.session.stop_listening()
            # инкремент длительности записи (только время диктофона, не открытой сессии)
            await self._persist_recorded_seconds(self.session.last_interval_seconds)
            self.session.last_interval_seconds = 0  # consumed → не дублировать в finalize
        self.clear_active_audio_source(connection_id)
        self._reset_recording_meta()
        await self.broadcast(self._recording_status_payload(False))
        if was_phone:
            await self.broadcast({
                "type": "phone_recording_stopped",
                "connection_id": connection_id,
            })

    # --- сообщения клиента (старые + новые алиасы) ---

    async def handle_client_message(self, connection_id: str, message: dict) -> None:
        try:
            await self._dispatch_client_message(connection_id, message)
        except Exception as e:
            # одно плохое сообщение не должно рвать соединение/комнату
            logger.warning(f"[room {self.meeting_id}] message handler error ({message.get('type')!r}): {e}")
            await self.send_to_connection(connection_id, {
                "type": "error", "message": "Не удалось обработать сообщение",
            })

    async def _dispatch_client_message(self, connection_id: str, message: dict) -> None:
        # Этап 9.1: фиксируем момент приёма сразу (для clock sync).
        server_receive_ms = int(time.time() * 1000)
        conn = self.connections.get(connection_id)
        if conn:
            conn.last_seen_at = datetime.utcnow()
        self.session.touch()
        t = message.get("type", "")
        if not isinstance(t, str):
            t = ""

        if t in ("start_audio", "start_listening"):
            await self.start_audio(connection_id)
        elif t in ("stop_audio", "stop_listening"):
            await self.stop_audio(connection_id)
        elif t in ("request_suggestion", "get_suggestions"):
            await self.session.request_manual_suggestion()
        elif t == "strengthen_position":
            await self.session.strengthen_position()
        elif t == "request_batch_finalize":
            await self.session.request_batch_finalize()
        elif t == "mark_speaker":
            name = message.get("name", "")
            if name:
                self.session.mark_speaker(name)
        elif t == "set_speaker_role":
            name = message.get("name", "")
            side = message.get("side", "")
            if name:
                self.session.set_speaker_role(name, side)
                conn = self.connections.get(connection_id)
                await self._persist_speaker_role(name, side, conn.user_id if conn else None)
                await self.broadcast({
                    "type": "speaker_roles_updated",
                    "roles": self.session.speaker_roles,
                })
                await self._schedule_multi_channel_reconciliation(reason="role")
        elif t == "update_meeting_context":
            await self._update_context(message)
        elif t == "change_role":
            await self._change_role(message, connection_id)
        elif t == "change_settings":
            self._change_settings(message)
            await self.send_to_connection(connection_id, {
                "type": "status", "message": "Настройки обновлены",
            })
        elif t == "clock_ping":
            # Этап 9.1: NTP-подобный ping → отвечаем pong с server-таймштампами.
            if conn:
                await self.send_to_connection(connection_id, {
                    "type": "clock_pong",
                    "seq": message.get("seq"),
                    "client_send_ms": message.get("client_send_ms"),
                    "server_receive_ms": server_receive_ms,
                    "server_send_ms": int(time.time() * 1000),
                })
        elif t == "clock_report":
            # Клиент посчитал offset/rtt по серии; сервер валидирует quality и хранит.
            await self._apply_clock_report(connection_id, message)
        elif t == "audio_level":
            # Этап 9: observer-метрики уровня звука (НЕ raw audio). Только от observer-устройств.
            if conn and conn.device_role == "observer":
                try:
                    # Этап 9.1: приводим client_ts_ms к server timeline по offset устройства.
                    client_ts_ms = message.get("client_ts_ms")
                    server_ts_ms = (
                        conn.to_server_ms(client_ts_ms)
                        if client_ts_ms is not None else None
                    )
                    self.observer.add_metric(
                        connection_id,
                        rms=message.get("rms", 0.0), peak=message.get("peak"),
                        vad=bool(message.get("vad", False)), seq=message.get("seq"),
                        client_ts_ms=client_ts_ms, server_ts=datetime.utcnow(),
                        server_ts_ms=server_ts_ms,
                    )
                except Exception:
                    pass
        elif t == "observer_side":
            if conn and conn.device_role == "observer":
                self.observer.set_side_hint(connection_id, message.get("side"))
        elif t == "enable_secondary_shadow":
            await self._enable_shadow(connection_id, message)
        elif t == "disable_secondary_shadow":
            if conn and conn.device_role == "secondary":
                self.shadow.disable_track(connection_id)
                await self.send_to_connection(connection_id, {
                    "type": "secondary_shadow_disabled", "connection_id": connection_id,
                })
                await self._broadcast_shadow_summary()
        elif t == "secondary_shadow_side":
            if conn and conn.device_role == "secondary":
                self.shadow.set_side_hint(connection_id, message.get("side"))
        elif t == "multi_channel_live_start":
            await self._handle_live_start(connection_id, message)
        elif t == "multi_channel_live_stop":
            if self._live_can_edit(connection_id) and self.multi_channel_live:
                await self.multi_channel_live.stop()
        elif t == "multi_channel_live_clear":
            if self._live_can_edit(connection_id) and self.multi_channel_live:
                await self.multi_channel_live.clear_results()
                await self._clear_multi_channel_reconciliation()
                await self.broadcast({"type": "multi_channel_reconciliation_state", "state": None})
        elif t == "multi_channel_live_get_snapshot":
            await self._send_live_snapshot(connection_id)
        elif t == "multi_channel_reconciliation_refresh":
            await self._schedule_multi_channel_reconciliation(reason="manual", immediate=True)
        elif t == "multi_channel_reconciliation_get_snapshot":
            await self._send_reconciliation_snapshot(connection_id)
        elif t == "transcription_promote":
            await self._handle_transcription_promote(connection_id, message)
        elif t == "transcription_fallback":
            await self._handle_transcription_fallback(connection_id, message)
        elif t == "get_transcription_authority":
            await self.send_to_connection(connection_id, {
                "type": "transcription_authority_state", **self.cutover.state_dict()})
        elif t in ("finalize_meeting", "save_to_history"):
            await self.finalize_meeting(connection_id, message.get("meeting_name"))
        else:
            await self.send_to_connection(connection_id, {
                "type": "error", "message": f"Unknown message type: {t}",
            })

    async def _enable_shadow(self, connection_id: str, message: dict) -> None:
        """Этап 9.2: включить secondary audio shadow для устройства."""
        conn = self.connections.get(connection_id)
        if conn is None or conn.device_role != "secondary":
            await self.send_to_connection(connection_id, {
                "type": "secondary_shadow_error", "reason": "wrong_device_role",
            })
            return
        sample_rate = message.get("sample_rate", self.shadow.target_sample_rate)
        channels = message.get("channels", 1)
        codec = message.get("codec", "pcm16")
        side_hint = message.get("side_hint")
        ok, reason = self.shadow.enable_track(
            connection_id, sample_rate=sample_rate, channels=channels,
            codec=codec, side_hint=side_hint,
        )
        if not ok:
            await self.send_to_connection(connection_id, {
                "type": "secondary_shadow_error", "reason": reason or "enable_failed",
            })
            return
        await self.send_to_connection(connection_id, {
            "type": "secondary_shadow_enabled",
            "connection_id": connection_id,
            "sample_rate": int(sample_rate),
            "channels": int(channels),
            "codec": str(codec).lower(),
            "target_sample_rate": self.shadow.target_sample_rate,
            "max_chunk_ms": self.shadow.max_chunk_ms,
            "max_chunk_bytes": self.shadow.max_chunk_bytes,
        })
        await self._broadcast_shadow_summary()

    async def _apply_clock_report(self, connection_id: str, message: dict) -> None:
        """Этап 9.1: сохранить присланный клиентом offset/rtt и эхо-статус качества."""
        conn = self.connections.get(connection_id)
        if conn is None:
            return
        try:
            offset_ms = float(message.get("offset_ms"))
            rtt_ms = max(0.0, float(message.get("rtt_ms")))
        except (TypeError, ValueError):
            return
        try:
            samples = int(message.get("samples_count") or 1)
        except (TypeError, ValueError):
            samples = 1
        quality = classify_quality(rtt_ms)  # не доверяем клиентскому ярлыку
        conn.clock = ClockSyncReport(
            offset_ms=offset_ms, rtt_ms=rtt_ms, quality=quality,
            samples_count=samples, updated_at=datetime.utcnow(),
        )
        await self.send_to_connection(connection_id, {
            "type": "clock_sync_status",
            "connection_id": connection_id,
            "offset_ms": offset_ms,
            "rtt_ms": rtt_ms,
            "quality": quality,
            "samples_count": samples,
        })

    async def _update_context(self, message: dict) -> None:
        title = message.get("title")
        topic = message.get("topic", "")
        notes = message.get("notes", "")
        negotiation_type = message.get("negotiation_type", "sale")
        meeting_role = message.get("meeting_role", "")
        opponent_weaknesses = message.get("opponent_weaknesses", "")
        self.session.update_meeting_context(topic, notes)
        self.session.negotiation_type = negotiation_type
        self.session.meeting_role = meeting_role
        self.session.opponent_weaknesses = opponent_weaknesses
        if title is not None:
            self.session.meeting_title = title
        # persist by meeting_id
        async with async_session() as db:
            meeting = (
                await db.execute(
                    select(MeetingSession).where(MeetingSession.id == self.meeting_id)
                )
            ).scalar_one_or_none()
            if meeting:
                meeting.meeting_topic = topic
                meeting.meeting_notes = notes
                meeting.negotiation_type = negotiation_type
                meeting.meeting_role = meeting_role
                meeting.opponent_weaknesses = opponent_weaknesses
                if title is not None:
                    meeting.title = title
                await db.commit()
        await self.broadcast({
            "type": "meeting_context_updated",
            "title": self.session.meeting_title,
            "topic": topic,
            "notes": notes,
            "negotiation_type": negotiation_type,
            "meeting_role": meeting_role,
            "opponent_weaknesses": opponent_weaknesses,
        })

    async def _change_role(self, message: dict, connection_id: str) -> None:
        role_id = message.get("role_id")
        if not role_id:
            return
        role_data = await load_role_by_id(role_id, self.owner_user_id or 0)
        if role_data:
            self.session.set_role(role_data)
            await self.send_to_connection(connection_id, {
                "type": "status", "message": f"Роль изменена: {role_data['name']}",
            })
        else:
            await self.send_to_connection(connection_id, {
                "type": "error", "message": "Роль не найдена",
            })

    def _change_settings(self, message: dict) -> None:
        for k in ("stt_provider", "llm_model", "temperature", "diarization", "silence_filter"):
            if k in message:
                self.settings[k] = message[k]
        if "llm_model" in message or "temperature" in message:
            openrouter_key = self.api_keys.get("openrouter", "")
            if openrouter_key:
                self.session.configure_llm(
                    api_key=openrouter_key,
                    model=self.settings["llm_model"],
                    temperature=self.settings["temperature"],
                )
        if "custom_suggestion_types" in message or "custom_trigger_keywords" in message:
            if "custom_suggestion_types" in message:
                self.settings["custom_suggestion_types"] = message["custom_suggestion_types"]
            if "custom_trigger_keywords" in message:
                self.settings["custom_trigger_keywords"] = message["custom_trigger_keywords"]
            apply_custom_hint_settings(self.session, self.settings)

    # --- финализация (по meeting_id) ---

    async def finalize_meeting(self, connection_id: str, meeting_name: str | None = None) -> None:
        """Завершить встречу по meeting_id: сохранить сегменты, выставить status=finalized."""
        conn = self.connections.get(connection_id)
        # право финализации: владелец встречи или текущий источник аудио (MVP)
        if (
            conn
            and self.owner_user_id
            and conn.user_id != self.owner_user_id
            and connection_id != self.active_audio_source
        ):
            await self.send_to_connection(connection_id, {
                "type": "error",
                "message": "Только создатель может завершить встречу",
            })
            return

        if self.session.is_listening:
            await self.session.stop_listening()
        self.active_audio_source = None
        self._reset_recording_meta()
        # Этап 9.8: остановить promoted live multi-channel (освободить provider-сокет и
        # глобальный слот лимитера) и детерминированно закрыть открытую эпоху транскрипта
        # на границе финализации (иначе утечка слота + epoch с end=NULL навсегда).
        try:
            await self.stop_multi_channel_live()
            await self._clear_multi_channel_reconciliation()
            await self.cutover.close_open_epoch_on_finalize()
        except Exception as e:
            logger.warning(f"[room {self.meeting_id}] cutover finalize teardown failed: {e}")
        await self._persist_segments(close=True, title_override=meeting_name)
        self.closed = True
        self.status = "finalized"

        # лучшее-усилие: локальное сохранение (как в старом save_to_history)
        try:
            await save_meeting_to_local(self.session.user_id, self.meeting_id)
        except Exception as e:
            logger.error(f"[room {self.meeting_id}] local save failed: {e}")

        await self.broadcast({"type": "meeting_saved", "meeting_id": self.meeting_id})
        await self.broadcast({
            "type": "room_status", "meeting_id": self.meeting_id, "status": "finalized",
        })

        # Этап 5: поставить встречу в очередь финализации (фоновый протокол)
        try:
            from .meeting_finalize import enqueue_finalization
            await enqueue_finalization(self.meeting_id)
            await self.broadcast({"type": "meeting_finalization_started", "meeting_id": self.meeting_id})
        except Exception as e:
            logger.error(f"[room {self.meeting_id}] enqueue finalization failed: {e}")

        # снять комнату с реестра (новые подключения создадут свежую при необходимости)
        room_registry.remove(self.meeting_id)

    async def _persist_speaker_role(self, speaker_label: str, side: str, user_id: int | None) -> None:
        """Сохранить роль спикера в БД (source of truth). Ошибка не ломает live-сессию."""
        try:
            from .speaker_roles import upsert_role
            async with async_session() as db:
                await upsert_role(db, self.meeting_id, speaker_label,
                                  side=side, assigned_by_user_id=user_id)
                await db.commit()
        except Exception as e:
            logger.error(f"[room {self.meeting_id}] persist speaker role failed: {e}")

    async def _on_committed_segment(self, segment, role: str | None) -> None:
        """Единый committed-хук: observer-подсказка (независимо) + дерево общения."""
        try:
            await self._broadcast_observer_hint(segment)
        except Exception as e:
            logger.debug(f"[room {self.meeting_id}] observer hint failed: {e}")
        await self._on_committed_for_tree(segment, role)
        # Этап 9.7: новый committed primary → пересобрать reconciliation (если live идёт)
        await self._schedule_multi_channel_reconciliation(reason="committed")

    async def _broadcast_observer_hint(self, segment) -> None:
        """Сравнить уровни observer-устройств вокруг реплики и broadcast `segment_side_hint`."""
        if not self.observer.enabled:
            return
        seg_key = getattr(segment, "segment_id", None)
        center = getattr(segment, "wall_clock", None)
        if not seg_key or center is None:
            return
        hint = self.observer.compute_segment_hint(seg_key, center)
        if hint is None:
            return
        await self.broadcast({
            "type": "segment_side_hint",
            "meeting_id": self.meeting_id,
            "segment_key": hint.segment_key,
            "side": hint.side,
            "confidence": hint.confidence,
            "reason": hint.reason,
            "device_count": hint.device_count,
            "window_ms": hint.window_ms,
            "auto_apply": self.observer.auto_apply,
        })

    async def _on_committed_for_tree(self, segment, role: str | None) -> None:
        """Conversation Tree: upsert темы по committed-сегменту + broadcast обновления.

        Fire-and-forget из SessionManager. Любая ошибка не должна ломать комнату/STT.
        """
        if not self._tree_enabled:
            return
        try:
            from .conversation_tree import ConversationTreeService

            segment_id = (getattr(segment, "segment_id", None)
                          or f"legacy_{uuid.uuid4().hex[:12]}")
            speaker = (getattr(segment, "speaker_label", None) or getattr(segment, "speaker_id", None)
                       or getattr(segment, "speaker", None) or "")
            text = getattr(segment, "text", "") or ""
            start = getattr(segment, "start_time", 0) or 0
            timecode = f"{int(start)//60:02d}:{int(start)%60:02d}"

            async with async_session() as db:
                topic_out = await ConversationTreeService().update_from_transcript_segment(
                    db, self.meeting_id, segment_id=segment_id, speaker=speaker,
                    role=role, text=text, timecode=timecode,
                )
                await db.commit()
            if topic_out is None:
                return
            self._tree_version += 1
            await self.broadcast({
                "type": "conversation_tree_updated",
                "meeting_id": self.meeting_id,
                "topic": topic_out.model_dump(mode="json"),
                "tree_version": self._tree_version,
            })
        except Exception as e:
            logger.error(f"[room {self.meeting_id}] conversation tree update failed: {e}")

    async def _persist_recorded_seconds(self, delta_seconds: int) -> None:
        """Инкремент recorded_seconds встречи — только время активной записи (диктофон)."""
        if not delta_seconds or delta_seconds <= 0:
            return
        try:
            async with async_session() as db:
                await db.execute(
                    update(MeetingSession)
                    .where(MeetingSession.id == self.meeting_id)
                    .values(recorded_seconds=MeetingSession.recorded_seconds + delta_seconds)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"[room {self.meeting_id}] persist recorded_seconds failed: {e}")

    async def _archive_session_audio(self) -> None:
        """Задача 3: сбросить записанный PCM в WAV и поставить job сжатия+заливки в S3.

        Вызывается на финализации/опустошении комнаты. Идемпотентно по факту записи:
        после сброса заводится свежий рекордер (повторная запись в той же комнате — отдельный файл).
        Ошибка архивации никогда не ломает персист сегментов/финализацию.
        """
        rec = self.audio_recorder
        if not rec.has_audio:
            return
        pcm_path = rec.close_to_pcm()
        self.audio_recorder = SessionAudioRecorder(self.meeting_id)  # свежий для возможной до-записи
        if not pcm_path:
            return
        try:
            wav_path = await asyncio.to_thread(pcm_to_wav, pcm_path)
        except Exception as e:
            logger.error(f"[room {self.meeting_id}] wav wrap failed: {e}")
            return
        try:
            from .jobs import enqueue
            async with async_session() as db:
                await enqueue(db, "meeting_audio_archive", {
                    "meeting_id": self.meeting_id,
                    "user_id": self.owner_user_id,
                    "wav_path": wav_path,
                })
                await db.commit()
        except Exception as e:
            logger.error(f"[room {self.meeting_id}] enqueue audio archive failed: {e}")

    async def _persist_segments(self, close: bool, title_override: str | None = None) -> None:
        """Сохранить committed-сегменты этой встречи (skip duplicates). При close — закрыть встречу."""
        try:
            async with async_session() as db:
                meeting = (
                    await db.execute(
                        select(MeetingSession).where(MeetingSession.id == self.meeting_id)
                    )
                ).scalar_one_or_none()
                if meeting:
                    if title_override:
                        meeting.title = title_override
                    if close:
                        meeting.is_active = False
                        meeting.status = "finalized"
                        meeting.ended_at = datetime.utcnow()
                        meeting.live_segment_count = len(self.session.committed_segments)
                        # доначислить незакрытый интервал записи (финализация во время записи).
                        # stop_audio обнуляет last_interval_seconds после своего персиста — здесь
                        # учитываем только ещё не сохранённый интервал.
                        pending = getattr(self.session, "last_interval_seconds", 0) or 0
                        if pending > 0:
                            meeting.recorded_seconds = (meeting.recorded_seconds or 0) + pending
                            self.session.last_interval_seconds = 0
                        if not meeting.title:
                            if meeting.meeting_topic:
                                meeting.title = meeting.meeting_topic[:80]
                            else:
                                meeting.title = f"Встреча {meeting.started_at.strftime('%d.%m.%Y %H:%M')}"

                existing = await db.execute(
                    select(TranscriptSegmentRecord.segment_id).where(
                        TranscriptSegmentRecord.session_id == self.meeting_id
                    )
                )
                existing_ids = {row[0] for row in existing.all()}
                for seg in self.session.committed_segments:
                    if seg.segment_id in existing_ids:
                        continue
                    db.add(TranscriptSegmentRecord(
                        session_id=self.meeting_id,
                        segment_id=seg.segment_id,
                        text=seg.text,
                        start_time=seg.start_time,
                        end_time=seg.end_time,
                        wall_clock=seg.wall_clock,
                        speech_start_ms=getattr(seg, "speech_start_ms", None),
                        speech_end_ms=getattr(seg, "speech_end_ms", None),
                        speaker_id=seg.speaker_id,
                        speaker_label=seg.speaker_label,
                        origin=seg.origin.value if hasattr(seg.origin, "value") else str(seg.origin),
                        word_count=seg.word_count,
                        avg_logprob=seg.avg_logprob,
                        min_logprob=seg.min_logprob,
                        words_json=json.dumps(
                            [w.to_dict() for w in seg.words], ensure_ascii=False
                        ) if seg.words else None,
                    ))
                await db.commit()
        except Exception as e:
            logger.error(f"[room {self.meeting_id}] persist segments failed: {e}")
        # Задача 3: архив живого аудио (после сегментов; ошибки не ломают персист)
        await self._archive_session_audio()


class RoomRegistry:
    """In-memory реестр комнат: meeting_id -> MeetingRoom.

    Точка подмены на Redis/distributed-реестр. Ключ — meeting_id (не user_id):
    один пользователь может вести несколько встреч, одна встреча — несколько подключений.
    """

    def __init__(self):
        self._rooms: dict[int, MeetingRoom] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def get_or_create_room(self, meeting_id: int) -> MeetingRoom:
        room = self._rooms.get(meeting_id)
        if room is not None:
            return room
        lock = self._locks.setdefault(meeting_id, asyncio.Lock())
        async with lock:
            room = self._rooms.get(meeting_id)
            if room is None:
                room = await MeetingRoom.create(meeting_id)
                self._rooms[meeting_id] = room
        return room

    def get_room(self, meeting_id: int) -> MeetingRoom | None:
        return self._rooms.get(meeting_id)

    def remove(self, meeting_id: int) -> None:
        self._rooms.pop(meeting_id, None)
        self._locks.pop(meeting_id, None)

    async def remove_room_if_idle(self, meeting_id: int) -> bool:
        """Снять простаивающую комнату (нет соединений и не слушает), сохранив сегменты."""
        room = self._rooms.get(meeting_id)
        if room and not room.connections and not room.session.is_listening:
            await room._persist_segments(close=False)
            # Этап 9.6: остановить live multi-channel shadow (provider close + cancel tasks)
            try:
                await room.stop_multi_channel_live()
            except Exception:
                pass
            # Этап 9.7: отменить reconciliation task + очистить in-memory state
            try:
                await room._clear_multi_channel_reconciliation()
            except Exception:
                pass
            # Этап 9.5: отменить in-flight batch-STT jobs встречи (освободить snapshot/WAV)
            try:
                from .multi_channel_batch_jobs import batch_job_registry
                await batch_job_registry.cancel_meeting_jobs(meeting_id)
            except Exception:
                pass
            self.remove(meeting_id)
            return True
        return False


# Singleton in-memory registry (заменяется на Redis-backed позже)
room_registry = RoomRegistry()


async def compute_live_state(db, meeting, user_id: int) -> dict:
    """Live-состояние встречи для API (live-state / mobile detail).

    Вызывающая сторона обязана проверить доступ (user_can_access_meeting).
    """
    room = room_registry.get_room(meeting.id)
    connections = [c.to_dict() for c in room.connections.values()] if room else []
    active = room.active_audio_source if room else None
    can_record = await can_record_meeting(db, user_id, meeting.id)
    role = await current_user_meeting_role(db, user_id, meeting.id)

    phone_connected = bool(
        room and any(c.device_role == "phone" for c in room.connections.values())
    )
    desktop_connected = bool(
        room and any(c.device_role == "desktop" for c in room.connections.values())
    )
    phone_recording = False
    if room and active:
        src = room.connections.get(active)
        phone_recording = bool(
            src and src.device_role == "phone" and room.session.is_listening
        )

    return {
        "meeting_id": meeting.id,
        "status": meeting.status,
        "customer_id": meeting.customer_id,
        "object_id": meeting.object_id,
        "title": meeting.title,
        "can_current_user_access": True,
        "can_current_user_record": can_record,
        "current_user_role": role,
        "device_connections": connections,
        "active_audio_source": active,
        "phone_connected": phone_connected,
        "phone_recording": phone_recording,
        "desktop_connected": desktop_connected,
    }
