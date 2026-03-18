"""WebSocket handler for real-time meeting communication.

Single endpoint: /ws/meeting?token=<jwt>
Handles audio streaming, control messages, and pushes transcription/suggestions.
"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

logger = logging.getLogger("ai_helper.ws")

from ..auth.service import decode_token
from ..database import async_session
from ..models.user import User
from ..models.settings import UserSettings
from ..models.api_key import ApiKey
from ..models.meeting import MeetingSession, TranscriptSegmentRecord, MeetingDocumentRecord
from ..models.role import NegotiationRole
from ..services.session_manager import get_session_manager, remove_session_manager
from ..services.local_storage import save_meeting_to_local
from ..core.context.document_loader import MeetingDocument
from ..services.encryption import decrypt_api_key

router = APIRouter()


async def _authenticate_ws(token: str) -> User | None:
    """Authenticate WebSocket connection via JWT."""
    payload = decode_token(token)
    if not payload:
        return None

    user_id = int(payload["sub"])
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
    return None


async def _load_user_settings(user_id: int) -> dict:
    """Load user settings from database."""
    async with async_session() as db:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings:
            return {
                "stt_provider": settings.stt_provider,
                "llm_model": settings.llm_model,
                "temperature": settings.temperature,
                "user_role": settings.user_role,
                "use_streaming": settings.use_streaming,
                "diarization": settings.diarization,
                "silence_filter": settings.silence_filter,
                "custom_suggestion_types": settings.custom_suggestion_types,
                "custom_trigger_keywords": settings.custom_trigger_keywords,
            }
    return {
        "stt_provider": "deepgram",
        "llm_model": "google/gemini-3-flash-preview",
        "temperature": 0.7,
        "user_role": "gen_contractor",
        "use_streaming": True,
        "diarization": False,
        "silence_filter": False,
        "custom_suggestion_types": None,
        "custom_trigger_keywords": None,
    }


async def _load_api_keys() -> dict:
    """Load active API keys from database."""
    keys = {}
    async with async_session() as db:
        result = await db.execute(select(ApiKey).where(ApiKey.is_active == True))
        for key in result.scalars().all():
            try:
                keys[key.service] = decrypt_api_key(key.encrypted_key)
            except Exception:
                logger.error(f"Failed to decrypt key for {key.service}")
    return keys


async def _load_default_role(user_id: int) -> dict | None:
    """Load default (first) role for user, or None."""
    async with async_session() as db:
        result = await db.execute(
            select(NegotiationRole)
            .where(NegotiationRole.user_id == user_id)
            .order_by(NegotiationRole.is_default.desc())
            .limit(1)
        )
        role = result.scalar_one_or_none()
        if role:
            return {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "interests": role.interests,
                "opponents": role.opponents,
                "custom_instructions": role.custom_instructions,
            }
    return None


async def _load_role_by_id(role_id: int, user_id: int) -> dict | None:
    """Load specific role by ID."""
    async with async_session() as db:
        result = await db.execute(
            select(NegotiationRole).where(
                NegotiationRole.id == role_id,
                NegotiationRole.user_id == user_id,
            )
        )
        role = result.scalar_one_or_none()
        if role:
            return {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "interests": role.interests,
                "opponents": role.opponents,
                "custom_instructions": role.custom_instructions,
            }
    return None


async def _load_or_create_meeting_session(user_id: int, session) -> None:
    """Load active MeetingSession from DB or create one. Restores context."""
    async with async_session() as db:
        result = await db.execute(
            select(MeetingSession)
            .where(MeetingSession.user_id == user_id, MeetingSession.is_active == True)
            .order_by(MeetingSession.started_at.desc())
            .limit(1)
        )
        meeting = result.scalar_one_or_none()

        if meeting:
            session.document_loader.meeting_topic = meeting.meeting_topic or ""
            session.document_loader.meeting_notes = meeting.meeting_notes or ""
            session.negotiation_type = meeting.negotiation_type or "sale"
            session.meeting_role = meeting.meeting_role or ""
            session.opponent_weaknesses = meeting.opponent_weaknesses or ""
            session.meeting_title = meeting.title or ""
            session.db_session_id = meeting.id

            # Restore documents from DB if not already loaded
            if not session.document_loader.documents:
                doc_result = await db.execute(
                    select(MeetingDocumentRecord)
                    .where(MeetingDocumentRecord.session_id == meeting.id)
                )
                for d in doc_result.scalars().all():
                    session.document_loader.documents.append(
                        MeetingDocument(
                            filename=d.filename,
                            content=d.content,
                            doc_type=d.doc_type,
                            loaded_at=d.created_at,
                            page_count=d.page_count,
                        )
                    )
            return

        meeting = MeetingSession(user_id=user_id, is_active=True)
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        session.db_session_id = meeting.id


async def _finalize_session(session) -> None:
    """Persist committed segments and close MeetingSession on disconnect."""
    if not session.db_session_id:
        return
    try:
        async with async_session() as db:
            result = await db.execute(
                select(MeetingSession).where(MeetingSession.id == session.db_session_id)
            )
            meeting = result.scalar_one_or_none()
            if meeting:
                meeting.is_active = False
                meeting.ended_at = datetime.utcnow()
                meeting.live_segment_count = len(session.committed_segments)
                if not meeting.title:
                    if meeting.meeting_topic:
                        meeting.title = meeting.meeting_topic[:80]
                    else:
                        meeting.title = f"Встреча {meeting.started_at.strftime('%d.%m.%Y %H:%M')}"

            # Persist committed segments (skip duplicates)
            existing = await db.execute(
                select(TranscriptSegmentRecord.segment_id).where(
                    TranscriptSegmentRecord.session_id == session.db_session_id
                )
            )
            existing_ids = {row[0] for row in existing.all()}

            for seg in session.committed_segments:
                if seg.segment_id in existing_ids:
                    continue
                record = TranscriptSegmentRecord(
                    session_id=session.db_session_id,
                    segment_id=seg.segment_id,
                    text=seg.text,
                    start_time=seg.start_time,
                    end_time=seg.end_time,
                    wall_clock=seg.wall_clock,
                    speaker_id=seg.speaker_id,
                    speaker_label=seg.speaker_label,
                    origin=seg.origin.value if hasattr(seg.origin, 'value') else str(seg.origin),
                    word_count=seg.word_count,
                    avg_logprob=seg.avg_logprob,
                    min_logprob=seg.min_logprob,
                    words_json=json.dumps(
                        [w.to_dict() for w in seg.words], ensure_ascii=False
                    ) if seg.words else None,
                )
                db.add(record)

            await db.commit()
    except Exception as e:
        logger.error(f"Failed to finalize session {session.db_session_id}: {e}")


def _apply_custom_hint_settings(session, settings: dict):
    """Apply custom suggestion types and trigger keywords to session."""
    raw_types = settings.get("custom_suggestion_types")
    if raw_types:
        types = json.loads(raw_types) if isinstance(raw_types, str) else raw_types
        session.set_custom_suggestion_types(types)

    raw_keywords = settings.get("custom_trigger_keywords")
    if raw_keywords:
        keywords = json.loads(raw_keywords) if isinstance(raw_keywords, str) else raw_keywords
        session.set_custom_trigger_keywords(keywords)


@router.websocket("/ws/meeting")
async def meeting_websocket(websocket: WebSocket, token: str = Query(...)):
    """Main WebSocket endpoint for meeting sessions."""
    # Authenticate
    user = await _authenticate_ws(token)
    if not user:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await websocket.accept()
    logger.info(f"[WS] User {user.id} ({user.email}) connected")

    # Initialize session
    session = get_session_manager(user.id)
    await _load_or_create_meeting_session(user.id, session)
    settings = await _load_user_settings(user.id)
    api_keys = await _load_api_keys()

    # Configure LLM
    openrouter_key = api_keys.get("openrouter", "")
    if openrouter_key:
        session.configure_llm(
            api_key=openrouter_key,
            model=settings["llm_model"],
            temperature=settings["temperature"],
        )

    # Load negotiation role and configure prompts
    role_data = await _load_default_role(user.id)
    if role_data:
        session.set_role(role_data)

    # Apply custom suggestion types / trigger keywords
    _apply_custom_hint_settings(session, settings)

    # Set WebSocket send function
    async def ws_send(data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    session.set_ws_send(ws_send)

    # Send initial status
    await websocket.send_json({"type": "status", "message": "Подключено. Готов к работе."})

    # Send restored meeting context
    if session.document_loader.meeting_topic or session.document_loader.meeting_notes or session.meeting_role or session.opponent_weaknesses or session.negotiation_type != "sale" or session.meeting_title:
        await websocket.send_json({
            "type": "meeting_context",
            "title": session.meeting_title,
            "topic": session.document_loader.meeting_topic,
            "notes": session.document_loader.meeting_notes,
            "negotiation_type": session.negotiation_type,
            "meeting_role": session.meeting_role,
            "opponent_weaknesses": session.opponent_weaknesses,
        })

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.receive":
                if "bytes" in message and message["bytes"]:
                    # Binary frame = audio data
                    if session.is_listening and session.audio_queue:
                        session.touch()
                        await session.audio_queue.put(
                            (datetime.now(), message["bytes"])
                        )
                elif "text" in message and message["text"]:
                    # JSON control message
                    try:
                        data = json.loads(message["text"])
                        await _handle_control_message(
                            session, data, settings, api_keys, websocket
                        )
                    except json.JSONDecodeError:
                        await websocket.send_json(
                            {"type": "error", "message": "Invalid JSON"}
                        )

            elif message["type"] == "websocket.disconnect":
                break

    except WebSocketDisconnect:
        logger.info(f"[WS] User {user.id} disconnected")
    except Exception as e:
        logger.info(f"[WS] Error for user {user.id}: {e}")
    finally:
        # Stop listening if active
        if session.is_listening:
            await session.stop_listening()
        # НЕ финализируем — сессия остаётся активной для реконнекта
        logger.info(f"[WS] User {user.id} disconnected, session preserved")


async def _handle_control_message(
    session, data: dict, settings: dict, api_keys: dict, websocket: WebSocket
):
    """Route control messages to session manager methods."""
    msg_type = data.get("type", "")
    session.touch()
    logger.info(f"[WS] Control message: {msg_type}")

    if msg_type == "start_listening":
        await session.start_listening(
            stt_provider=settings["stt_provider"],
            api_keys=api_keys,
            diarization=settings.get("diarization", True),
        )

    elif msg_type == "stop_listening":
        await session.stop_listening()

    elif msg_type == "request_suggestion":
        await session.request_manual_suggestion()

    elif msg_type == "strengthen_position":
        await session.strengthen_position()

    elif msg_type == "mark_speaker":
        name = data.get("name", "")
        if name:
            session.mark_speaker(name)

    elif msg_type == "set_speaker_role":
        name = data.get("name", "")
        side = data.get("side", "")
        if name:
            session.set_speaker_role(name, side)
            await websocket.send_json({
                "type": "speaker_roles_updated",
                "roles": session.speaker_roles,
            })

    elif msg_type == "update_meeting_context":
        title = data.get("title")
        topic = data.get("topic", "")
        notes = data.get("notes", "")
        negotiation_type = data.get("negotiation_type", "sale")
        meeting_role = data.get("meeting_role", "")
        opponent_weaknesses = data.get("opponent_weaknesses", "")
        session.update_meeting_context(topic, notes)
        session.negotiation_type = negotiation_type
        session.meeting_role = meeting_role
        session.opponent_weaknesses = opponent_weaknesses
        if title is not None:
            session.meeting_title = title
        # Persist to DB
        if session.db_session_id:
            async with async_session() as db:
                result = await db.execute(
                    select(MeetingSession).where(MeetingSession.id == session.db_session_id)
                )
                meeting = result.scalar_one_or_none()
                if meeting:
                    meeting.meeting_topic = topic
                    meeting.meeting_notes = notes
                    meeting.negotiation_type = negotiation_type
                    meeting.meeting_role = meeting_role
                    meeting.opponent_weaknesses = opponent_weaknesses
                    if title is not None:
                        meeting.title = title
                    await db.commit()

    elif msg_type == "change_role":
        role_id = data.get("role_id")
        if role_id:
            # Need user_id — extract from websocket state
            user_id = session.user_id
            role_data = await _load_role_by_id(role_id, user_id)
            if role_data:
                session.set_role(role_data)
                await websocket.send_json(
                    {"type": "status", "message": f"Роль изменена: {role_data['name']}"}
                )
            else:
                await websocket.send_json(
                    {"type": "error", "message": "Роль не найдена"}
                )

    elif msg_type == "save_to_history":
        meeting_name = data.get("meeting_name")
        meeting_id = session.db_session_id
        # Update title if provided
        if meeting_name and meeting_id:
            async with async_session() as db:
                result = await db.execute(
                    select(MeetingSession).where(MeetingSession.id == meeting_id)
                )
                m = result.scalar_one_or_none()
                if m:
                    m.title = meeting_name
                    await db.commit()
        await _finalize_session(session)
        # Save to local storage (best-effort)
        if meeting_id:
            try:
                await save_meeting_to_local(session.user_id, meeting_id)
            except Exception as e:
                logger.error(f"Local storage save failed: {e}")
        remove_session_manager(session.user_id)
        await websocket.send_json({"type": "meeting_saved", "meeting_id": meeting_id})

    elif msg_type == "request_batch_finalize":
        await session.request_batch_finalize()

    elif msg_type == "change_settings":
        # Update settings in-memory for this session
        if "stt_provider" in data:
            settings["stt_provider"] = data["stt_provider"]
        if "llm_model" in data:
            settings["llm_model"] = data["llm_model"]
        if "temperature" in data:
            settings["temperature"] = data["temperature"]
        if "diarization" in data:
            settings["diarization"] = data["diarization"]
        if "silence_filter" in data:
            settings["silence_filter"] = data["silence_filter"]

        # Reconfigure LLM if model or temperature changed
        if "llm_model" in data or "temperature" in data:
            openrouter_key = api_keys.get("openrouter", "")
            if openrouter_key:
                session.configure_llm(
                    api_key=openrouter_key,
                    model=settings["llm_model"],
                    temperature=settings["temperature"],
                )

        # Apply custom hint settings if changed
        if "custom_suggestion_types" in data or "custom_trigger_keywords" in data:
            if "custom_suggestion_types" in data:
                settings["custom_suggestion_types"] = data["custom_suggestion_types"]
            if "custom_trigger_keywords" in data:
                settings["custom_trigger_keywords"] = data["custom_trigger_keywords"]
            _apply_custom_hint_settings(session, settings)

        await websocket.send_json(
            {"type": "status", "message": "Настройки обновлены"}
        )

    else:
        await websocket.send_json(
            {"type": "error", "message": f"Unknown message type: {msg_type}"}
        )
