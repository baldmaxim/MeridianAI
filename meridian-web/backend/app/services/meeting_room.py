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
import uuid
from datetime import datetime

from sqlalchemy import select

from ..database import async_session
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
from .access import can_record_meeting, current_user_meeting_role
from .document_context import build_meeting_doc_context
from .knowledge_context import build_meeting_knowledge_context
from .previous_meeting_context import get_previous_meeting_context_for_prompt
from .ai_settings import snapshot_for_meeting

logger = logging.getLogger("meridian.room")

VALID_DEVICE_ROLES = ("desktop", "phone", "viewer", "participant")
# роли, которым в Этапе 2 разрешено быть источником аудио
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

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "user_id": self.user_id,
            "device_role": self.device_role,
            "can_send_audio": self.can_send_audio,
            "is_active_audio_source": self.is_active_audio_source,
            "connected_at": self.connected_at.isoformat(),
        }


class MeetingRoom:
    """Live-комната встречи: реестр соединений + единый STT/LLM-движок (SessionManager)."""

    def __init__(self, meeting_id: int, owner_user_id: int | None, status: str | None):
        self.meeting_id = meeting_id
        self.owner_user_id = owner_user_id
        self.status = status
        self.connections: dict[str, MeetingConnection] = {}
        self.active_audio_source: str | None = None  # connection_id
        self.settings: dict = {}
        self.api_keys: dict = {}
        self.closed = False
        # STT/LLM-движок этой встречи; вывод → broadcast
        self.session = SessionManager(owner_user_id or 0)
        self.session.db_session_id = meeting_id
        # Conversation Tree (дерево общения)
        self._tree_enabled = True
        self._tree_version = 0

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
        # Conversation Tree: обновление дерева общения по committed-сегментам
        room._tree_enabled = bool(ai_resolved.get("conversation_tree_enabled", True))
        room.session.set_committed_hook(room._on_committed_for_tree)
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
        await conn.send_json({
            "type": "recording_status",
            "recording": self.session.is_listening,
            "active_audio_source": self.active_audio_source,
        })
        # текущие роли спикеров (восстановление после refresh)
        if self.session.speaker_roles:
            await conn.send_json({
                "type": "speaker_roles_updated",
                "roles": self.session.speaker_roles,
            })
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
        if self.active_audio_source == connection_id:
            # источник аудио отключился — НЕ финализируем встречу, только чистим источник
            was_phone = conn.device_role == "phone"
            self.active_audio_source = None
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

    async def handle_audio_frame(self, connection_id: str, data: bytes) -> None:
        """Бинарный аудио-фрейм принимается ТОЛЬКО от активного источника."""
        if connection_id != self.active_audio_source:
            return
        if self.session.is_listening and self.session.audio_queue:
            self.session.touch()
            await self.session.audio_queue.put((datetime.now(), data))

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
        if not self.session.is_listening:
            await self.session.start_listening(
                stt_provider=self.settings.get("stt_provider", "deepgram"),
                api_keys=self.api_keys,
                diarization=self.settings.get("diarization", True),
            )
        await self.broadcast({
            "type": "recording_status",
            "recording": True,
            "active_audio_source": self.active_audio_source,
        })
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
        self.clear_active_audio_source(connection_id)
        await self.broadcast({
            "type": "recording_status",
            "recording": False,
            "active_audio_source": None,
        })
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
        elif t == "update_meeting_context":
            await self._update_context(message)
        elif t == "change_role":
            await self._change_role(message, connection_id)
        elif t == "change_settings":
            self._change_settings(message)
            await self.send_to_connection(connection_id, {
                "type": "status", "message": "Настройки обновлены",
            })
        elif t in ("finalize_meeting", "save_to_history"):
            await self.finalize_meeting(connection_id, message.get("meeting_name"))
        else:
            await self.send_to_connection(connection_id, {
                "type": "error", "message": f"Unknown message type: {t}",
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
