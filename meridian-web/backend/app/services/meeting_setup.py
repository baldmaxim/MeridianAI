"""Общие помощники настройки live-сессии (Этап 2).

Вынесены из ws/handler.py, чтобы и старый WS-эндпоинт, и MeetingRoom использовали
один код конфигурации SessionManager (без циклических импортов ws<->services).
"""

import json
import logging

from sqlalchemy import select

from ..database import async_session
from ..auth.service import decode_token
from ..models.user import User
from ..models.settings import UserSettings
from ..models.role import NegotiationRole

logger = logging.getLogger("meridian.ws")


DEFAULT_SETTINGS = {
    "stt_provider": "deepgram",
    "llm_model": "google/gemini-3-flash-preview",
    "temperature": 0.7,
    "user_role": "gen_contractor",
    "use_streaming": True,
    "diarization": True,
    "diarization_max_speakers": 3,
    "silence_filter": False,
    "custom_suggestion_types": None,
    "custom_trigger_keywords": None,
}


async def authenticate_ws(token: str) -> User | None:
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


async def load_user_settings(user_id: int | None) -> dict:
    """Load user settings from DB, falling back to defaults."""
    if user_id is None:
        return dict(DEFAULT_SETTINGS)
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
                "diarization_max_speakers": settings.diarization_max_speakers,
                "silence_filter": settings.silence_filter,
                "custom_suggestion_types": settings.custom_suggestion_types,
                "custom_trigger_keywords": settings.custom_trigger_keywords,
            }
    return dict(DEFAULT_SETTINGS)


async def load_default_role(user_id: int | None) -> dict | None:
    """Load default (first) role for user, or None."""
    if user_id is None:
        return None
    async with async_session() as db:
        result = await db.execute(
            select(NegotiationRole)
            .where(NegotiationRole.user_id == user_id)
            .order_by(NegotiationRole.is_default.desc())
            .limit(1)
        )
        role = result.scalar_one_or_none()
        if role:
            return _role_to_dict(role)
    return None


async def load_role_by_id(role_id: int, user_id: int) -> dict | None:
    """Load specific role by ID for a user."""
    async with async_session() as db:
        result = await db.execute(
            select(NegotiationRole).where(
                NegotiationRole.id == role_id,
                NegotiationRole.user_id == user_id,
            )
        )
        role = result.scalar_one_or_none()
        if role:
            return _role_to_dict(role)
    return None


def _role_to_dict(role: NegotiationRole) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "interests": role.interests,
        "opponents": role.opponents,
        "custom_instructions": role.custom_instructions,
    }


def apply_custom_hint_settings(session, settings: dict) -> None:
    """Apply custom suggestion types and trigger keywords to a SessionManager."""
    raw_types = settings.get("custom_suggestion_types")
    if raw_types:
        types = json.loads(raw_types) if isinstance(raw_types, str) else raw_types
        session.set_custom_suggestion_types(types)

    raw_keywords = settings.get("custom_trigger_keywords")
    if raw_keywords:
        keywords = json.loads(raw_keywords) if isinstance(raw_keywords, str) else raw_keywords
        session.set_custom_trigger_keywords(keywords)
