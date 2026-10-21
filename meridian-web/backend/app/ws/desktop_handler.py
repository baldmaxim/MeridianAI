# -*- coding: utf-8 -*-
"""WebSocket десктоп-приложения: живой режим встречи.

/ws/desktop/meetings/{meeting_id}?token=<токен устройства>

Приложение распознаёт речь у себя и шлёт сюда готовые фразы (`transcript_segments`), а в ответ
получает те же ИИ-подсказки, что и веб-клиент: сокет подключается к общей MeetingRoom встречи
(room_registry) без аудио. Фразы сохраняются тем же upsert, что и REST
`PUT /api/desktop/meetings/{id}/segments`, и подаются в историю комнаты как финальные сегменты
от STT — оттуда их берут ручные подсказки и автоподсказки signal engine.

Сокет всегда принимается (accept), а отказ отдаётся закрытием с кодом: до accept клиент увидел бы
только HTTP 403 и не узнал причину. Коды: 4401 — токен не принят, 4404 — встреча не найдена,
4409 — встреча уже финализирована.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select

from ..core.transcription.models import CommittedSegment
from ..database import async_session
from ..models.meeting import MeetingSession, TranscriptSegmentRecord
from ..schemas.desktop import SegmentsRequest
from ..services import desktop_sync as sync
from ..services.desktop_devices import authenticate_device, touch_device
from ..services.meeting_room import MeetingConnection, MeetingRoom, room_registry

logger = logging.getLogger("meridian.ws.desktop")

router = APIRouter()

CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_MEETING_CLOSED = 4409

# Сторона по каналу приложения: микрофон — «мы», звук системы — «оппонент», mixed — без стороны.
CHANNEL_SIDES = {"mic": "self", "system": "opponent"}
SPEAKER_ID_SIDES = {sync.CHANNEL_SPEAKERS[ch][0]: side for ch, side in CHANNEL_SIDES.items()}

# Эти сообщения уходят в общий диспетчер комнаты; остальное от приложения не принимается.
SUGGESTION_TYPES = ("request_suggestion", "strengthen_position")
AUDIO_CONTROL_TYPES = ("start_listening", "stop_listening", "start_audio", "stop_audio")


# ── флаг is_active на время подключения ───────────────────────────────────


@dataclass
class _LiveState:
    clients: int
    was_active: bool


# meeting_id -> сколько сокетов приложения держат встречу «живой» и каким был is_active до них
_live: dict[int, _LiveState] = {}
_live_lock = asyncio.Lock()


async def _mark_live(meeting_id: int) -> None:
    """На время подключения приложения встреча считается идущей (is_active=True)."""
    async with _live_lock:
        state = _live.get(meeting_id)
        if state is not None:
            state.clients += 1
            return
        async with async_session() as db:
            meeting = await db.get(MeetingSession, meeting_id)
            was_active = bool(meeting and meeting.is_active)
            if meeting is not None and not was_active:
                meeting.is_active = True
                await db.commit()
        _live[meeting_id] = _LiveState(clients=1, was_active=was_active)


async def _release_live(meeting_id: int) -> None:
    """Последний сокет приложения ушёл — вернуть is_active как было. Финализацию не делаем."""
    async with _live_lock:
        state = _live.get(meeting_id)
        if state is None:
            return
        state.clients -= 1
        if state.clients > 0:
            return
        del _live[meeting_id]
        if state.was_active:
            return
        try:
            async with async_session() as db:
                meeting = await db.get(MeetingSession, meeting_id)
                # Финализированную (приложением по REST или с сайта) не трогаем: там флаг уже сброшен.
                if meeting is not None and meeting.is_active and not sync.is_finalized(meeting):
                    meeting.is_active = False
                    await db.commit()
        except Exception:
            logger.exception("[WS desktop] не удалось вернуть is_active встрече %s", meeting_id)


# ── сегменты ──────────────────────────────────────────────────────────────


def _utc_naive_to_local(value: datetime) -> datetime:
    """Часы живой комнаты — datetime.now() (локальные naive), в БД — naive UTC."""
    return value.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def _committed(
    *, segment_id: str, text: str, start_time: float, end_time: float, wall_utc: datetime,
    speaker_id: str, speaker_label: str,
) -> tuple[CommittedSegment, str | None]:
    return CommittedSegment(
        segment_id=segment_id,
        text=text,
        start_time=start_time,
        end_time=end_time,
        wall_clock=_utc_naive_to_local(wall_utc),
        speaker_id=speaker_id,
        speaker_label=speaker_label,
        word_count=len(text.split()),
    ), SPEAKER_ID_SIDES.get(speaker_id)


async def _hydrate_room(room: MeetingRoom, meeting_id: int) -> None:
    """Досыпать в историю свежей комнаты уже принятые фразы приложения (без рассылки и подсказок).

    Комната живёт, пока есть соединения; после переподключения она новая и пустая, а ручной
    запрос подсказки смотрит именно в её историю.
    """
    async with async_session() as db:
        rows = (await db.execute(
            select(TranscriptSegmentRecord)
            .where(TranscriptSegmentRecord.session_id == meeting_id,
                   TranscriptSegmentRecord.origin == "desktop")
            .order_by(TranscriptSegmentRecord.start_time, TranscriptSegmentRecord.id)
        )).scalars().all()
    items = [
        _committed(
            segment_id=r.segment_id, text=r.text, start_time=r.start_time, end_time=r.end_time,
            wall_utc=r.wall_clock, speaker_id=r.speaker_id, speaker_label=r.speaker_label or r.speaker_id,
        )
        for r in rows if (r.text or "").strip()
    ]
    if items:
        await room.ingest_external_segments(items, replay=True)


# ── авторизация ───────────────────────────────────────────────────────────


@dataclass
class _Authorized:
    user_id: int
    device_name: str


async def _still_authorized(token: str) -> bool:
    """Токен не отозван, пользователь активен (проверка на каждом сообщении, не только на входе)."""
    async with async_session() as db:
        return await authenticate_device(db, token) is not None


async def _reject(websocket: WebSocket, close_code: int, code: str, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "code": code, "message": message})
        await websocket.close(code=close_code, reason=message[:60])
    except Exception:
        pass


async def _authorize(websocket: WebSocket, meeting_id: int, token: str) -> _Authorized | None:
    """Токен устройства + встреча этого пользователя, не финализированная. None — сокет закрыт."""
    async with async_session() as db:
        auth = await authenticate_device(db, token)
        if auth is None:
            logger.warning("[WS desktop] токен устройства не принят")
            await _reject(websocket, CLOSE_UNAUTHORIZED, "unauthorized", "Токен устройства не принят")
            return None
        user_id, device_name = auth.user.id, auth.device.name
        await touch_device(db, auth.device)
        found = await sync.get_linked_meeting(db, user_id, meeting_id)
        if found is None:
            await _reject(websocket, CLOSE_NOT_FOUND, "meeting_not_found", "Встреча не найдена")
            return None
        if sync.is_finalized(found[0]):
            await _reject(websocket, CLOSE_MEETING_CLOSED, "meeting_closed", "Встреча уже финализирована")
            return None
    return _Authorized(user_id=user_id, device_name=device_name)


# ── соединение ────────────────────────────────────────────────────────────


async def _handle_segments(
    websocket: WebSocket, room: MeetingRoom, meeting_id: int, user_id: int, data: dict,
) -> bool:
    """transcript_segments: сохранить (upsert) и подать в комнату. False — сокет закрыт."""
    try:
        request = SegmentsRequest.model_validate({"segments": data.get("segments")})
    except ValidationError:
        await websocket.send_json({
            "type": "error", "code": "invalid_segments",
            "message": "transcript_segments: неверный формат segments",
        })
        return True

    async with async_session() as db:
        found = await sync.get_linked_meeting(db, user_id, meeting_id)
        if found is None:
            await _reject(websocket, CLOSE_NOT_FOUND, "meeting_not_found", "Встреча не найдена")
            return False
        meeting, link = found
        incoming = [
            sync.SegmentIn(
                client_segment_id=s.client_segment_id, text=s.text, start_time=s.start_time,
                end_time=s.end_time, wall_clock=s.wall_clock, channel=s.channel,
                speaker_label=s.speaker_label,
            )
            for s in request.segments
        ]
        try:
            created, updated = await sync.upsert_segments(db, meeting, link, incoming)
        except sync.DesktopMeetingClosedError:
            await _reject(websocket, CLOSE_MEETING_CLOSED, "meeting_closed", "Встреча уже финализирована")
            return False
        await db.commit()

        items: list[tuple[CommittedSegment, str | None]] = []
        for seg in incoming:
            text = (seg.text or "").strip()
            if not text:
                continue
            speaker_id, label = sync._speaker_for(seg)
            wall_utc = sync.to_naive_utc(seg.wall_clock) or (
                meeting.started_at + timedelta(seconds=seg.start_time))
            items.append(_committed(
                segment_id=sync.segment_server_id(link.client_uuid, seg.client_segment_id),
                text=text, start_time=seg.start_time, end_time=seg.end_time, wall_utc=wall_utc,
                speaker_id=speaker_id, speaker_label=label,
            ))

    room.session.touch()
    await room.ingest_external_segments(items)
    await websocket.send_json({
        "type": "segments_ack",
        "client_segment_ids": [s.client_segment_id for s in request.segments],
        "created": created,
        "updated": updated,
    })
    return True


@router.websocket("/ws/desktop/meetings/{meeting_id}")
async def desktop_meeting_ws(websocket: WebSocket, meeting_id: int, token: str = Query("")):
    await websocket.accept()
    authorized = await _authorize(websocket, meeting_id, token)
    if authorized is None:
        return

    await _mark_live(meeting_id)
    room: MeetingRoom | None = None
    conn: MeetingConnection | None = None
    pending: dict[str, asyncio.Task] = {}
    try:
        room = await room_registry.get_or_create_room(meeting_id)
        await _hydrate_room(room, meeting_id)

        async def send_json(data: dict) -> None:
            try:
                await websocket.send_json(data)
            except Exception:
                pass

        # can_record=False: источником аудио приложение не бывает, звука не шлёт.
        conn = MeetingConnection(
            meeting_id, authorized.user_id, "desktop", send_json,
            can_record=False, device_label=f"Приложение · {authorized.device_name}"[:120],
        )
        await room.add_connection(conn)
        logger.info("[WS desktop] user %s joined meeting %s (conn %s)",
                    authorized.user_id, meeting_id, conn.connection_id)

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                await send_json({"type": "error", "code": "audio_not_supported",
                                 "message": "Аудио не принимается: шлите transcript_segments"})
                continue
            raw = message.get("text")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
            if not isinstance(data, dict):
                await send_json({"type": "error", "code": "invalid_json", "message": "Invalid JSON"})
                continue

            msg_type = data.get("type")
            if msg_type == "ping":
                await send_json({"type": "pong", "ts": data.get("ts")})
                continue
            if not await _still_authorized(token):
                await _reject(websocket, CLOSE_UNAUTHORIZED, "unauthorized", "Токен устройства не принят")
                break

            if msg_type == "transcript_segments":
                if not await _handle_segments(websocket, room, meeting_id, authorized.user_id, data):
                    break
            elif msg_type in SUGGESTION_TYPES:
                # LLM отвечает десятки секунд — в фоне, чтобы не вставали ping и сегменты.
                running = pending.get(msg_type)
                if running is not None and not running.done():
                    await send_json({"type": "status", "message": "Подсказка уже формируется"})
                    continue
                pending[msg_type] = asyncio.create_task(
                    room.handle_client_message(conn.connection_id, {"type": msg_type})
                )
            elif msg_type in AUDIO_CONTROL_TYPES:
                await send_json({"type": "error", "code": "audio_not_supported",
                                 "message": "Аудио-управление недоступно: приложение шлёт готовые фразы"})
            else:
                await send_json({"type": "error", "code": "unsupported_type",
                                 "message": f"Unknown message type: {msg_type}"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("[WS desktop] meeting %s: ошибка соединения", meeting_id)
    finally:
        for task in pending.values():
            task.cancel()
        if room is not None and conn is not None:
            await room.remove_connection(conn.connection_id)
            logger.info("[WS desktop] user %s left meeting %s", authorized.user_id, meeting_id)
            try:
                await room_registry.remove_room_if_idle(meeting_id)
            except Exception:
                logger.warning("[WS desktop] idle room reap failed for meeting %s", meeting_id)
        await _release_live(meeting_id)
