"""WebSocket handlers for real-time meeting communication (Этап 2).

Endpoints:
  - /ws/meetings/{meeting_id}?token=<jwt>&device_role=desktop|phone|viewer|participant
    Live-сессия привязана к meeting_id (multi-device). Доступ проверяется через
    user_can_access_meeting.
  - /ws/meeting?token=<jwt>  (DEPRECATED)
    Старый desktop-сценарий. Backward-compat shim: резолвит активную/draft встречу
    пользователя и подключает её к MeetingRoom как device_role=desktop.

Оба эндпоинта используют общий serve_meeting_connection поверх MeetingRoom.
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

logger = logging.getLogger("meridian.ws")

from ..config import get_settings
from ..database import async_session
from ..models.meeting import MeetingSession
from ..services.meeting_setup import authenticate_ws
from ..services.meeting_room import (
    room_registry,
    MeetingConnection,
    VALID_DEVICE_ROLES,
)
from ..services.access import user_can_access_meeting, can_record_meeting

router = APIRouter()


async def serve_meeting_connection(
    websocket: WebSocket, user, meeting_id: int, device_role: str
) -> None:
    """Общий lifecycle одного соединения поверх MeetingRoom.

    Предполагается, что аутентификация и проверка доступа уже выполнены.
    """
    await websocket.accept()
    room = await room_registry.get_or_create_room(meeting_id)

    # Этап 3: право записи (стать источником аудио) — отдельно от доступа на просмотр
    async with async_session() as db:
        can_record = await can_record_meeting(db, user.id, meeting_id)

    async def send_json(data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    conn = MeetingConnection(meeting_id, user.id, device_role, send_json, can_record=can_record)
    await room.add_connection(conn)
    logger.info(
        f"[WS] user {user.id} joined meeting {meeting_id} as {device_role} "
        f"(conn {conn.connection_id})"
    )

    max_frame = get_settings().ws_max_binary_frame_bytes
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.receive":
                if "bytes" in message and message["bytes"]:
                    frame = message["bytes"]
                    if len(frame) > max_frame:
                        # слишком большой аудио-фрейм — отклоняем, соединение живёт
                        await send_json({"type": "error",
                                         "message": "Аудио-фрейм превышает допустимый размер"})
                        continue
                    await room.handle_audio_frame(conn.connection_id, frame)
                elif "text" in message and message["text"]:
                    try:
                        data = json.loads(message["text"])
                    except json.JSONDecodeError:
                        await send_json({"type": "error", "message": "Invalid JSON"})
                        continue
                    await room.handle_client_message(conn.connection_id, data)
            elif message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.info(f"[WS] meeting {meeting_id} conn {conn.connection_id} error: {e}")
    finally:
        await room.remove_connection(conn.connection_id)
        logger.info(
            f"[WS] user {user.id} left meeting {meeting_id} (conn {conn.connection_id})"
        )
        # §16/Этап 10: освободить пустую неактивную комнату (сегменты сохраняются внутри)
        try:
            await room_registry.remove_room_if_idle(meeting_id)
        except Exception:
            logger.warning("[WS] idle room reap failed for meeting %s", meeting_id)


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_room_ws(
    websocket: WebSocket,
    meeting_id: int,
    token: str = Query(...),
    device_role: str = Query("desktop"),
):
    """Live WebSocket по конкретной встрече (multi-device)."""
    user = await authenticate_ws(token)
    if not user:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    if device_role not in VALID_DEVICE_ROLES:
        device_role = "viewer"

    async with async_session() as db:
        allowed = await user_can_access_meeting(db, user.id, meeting_id)
    if not allowed:
        await websocket.close(code=4003, reason="No access to this meeting")
        return

    await serve_meeting_connection(websocket, user, meeting_id, device_role)


async def _resolve_user_active_meeting(user_id: int) -> int:
    """Найти самую свежую активную встречу пользователя или создать новый draft.

    Сохраняет старое поведение /ws/meeting (без customer_id/object_id).
    """
    async with async_session() as db:
        meeting = (
            await db.execute(
                select(MeetingSession)
                .where(MeetingSession.user_id == user_id, MeetingSession.is_active == True)
                .order_by(MeetingSession.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if meeting:
            return meeting.id
        meeting = MeetingSession(
            user_id=user_id,
            created_by_user_id=user_id,
            is_active=True,
            status="active",
        )
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        return meeting.id


@router.websocket("/ws/meeting")
async def meeting_websocket_legacy(websocket: WebSocket, token: str = Query(...)):
    """DEPRECATED: старый endpoint. Резолвит/создаёт встречу и подключает к MeetingRoom."""
    user = await authenticate_ws(token)
    if not user:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    logger.warning(
        "[WS] /ws/meeting deprecated — используйте /ws/meetings/{meeting_id}; "
        f"user={user.id}"
    )
    meeting_id = await _resolve_user_active_meeting(user.id)
    await serve_meeting_connection(websocket, user, meeting_id, "desktop")
