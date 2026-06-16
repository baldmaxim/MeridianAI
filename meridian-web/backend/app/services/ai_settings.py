"""AISettingsResolver (Этап 9): профили → нормализованные настройки + снапшот встречи.

Приоритет резолвинга: snapshot встречи > профиль встречи > default-профиль пользователя > config/.env.
Снапшот «замораживает» настройки на время live-встречи (чтобы не «скакали»). Секреты не хранятся.
"""

import json
import re
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.ai_settings import AISettingsProfile
from ..models.meeting import MeetingSession

logger = logging.getLogger("meridian.ai_settings")

MODES = ("fast", "balanced", "deep")
DEFAULT_LIVE_MODEL = "google/gemini-3-flash-preview"

# Лимиты/карточки по режиму (apply_mode_defaults заполняет колонки профиля)
MODE_DEFAULTS = {
    "fast":     {"max_auto_cards": 1, "max_manual_cards": 3, "auto_suggestion_min_interval_seconds": 30,
                 "document_context_max_chunks": 3, "document_context_max_chars": 6000,
                 "previous_context_max_meetings": 2, "previous_context_max_chars": 8000,
                 "knowledge_context_max_items": 6},
    "balanced": {"max_auto_cards": 2, "max_manual_cards": 5, "auto_suggestion_min_interval_seconds": 20,
                 "document_context_max_chunks": 6, "document_context_max_chars": 14000,
                 "previous_context_max_meetings": 5, "previous_context_max_chars": 20000,
                 "knowledge_context_max_items": 12},
    "deep":     {"max_auto_cards": 2, "max_manual_cards": 5, "auto_suggestion_min_interval_seconds": 20,
                 "document_context_max_chunks": 10, "document_context_max_chars": 24000,
                 "previous_context_max_meetings": 5, "previous_context_max_chars": 28000,
                 "knowledge_context_max_items": 20},
}

# max_tokens по режиму. live auto всегда короткий; deep усиливает manual/strengthen/finalization
MODE_TOKENS = {
    "fast":     {"auto": 300, "manual": 900, "strengthen": 1000, "finalization": 4000},
    "balanced": {"auto": 600, "manual": 1400, "strengthen": 1500, "finalization": 6000},
    "deep":     {"auto": 600, "manual": 2200, "strengthen": 2600, "finalization": 8000},
}

STT_PROVIDERS = ("deepgram", "elevenlabs", "gemini")
LLM_PROVIDERS = ("openrouter",)
_MODEL_RE = re.compile(r"^[A-Za-z0-9_.:/\-]{1,100}$")


def valid_model_string(v: str | None) -> bool:
    return v is None or v == "" or bool(_MODEL_RE.match(v))


# --- baseline из config/.env ---

def config_baseline() -> dict:
    s = get_settings()
    return {
        "stt_provider": "deepgram",
        "stt_model": None,
        "llm_provider": "openrouter",
        "live_suggestion_model": DEFAULT_LIVE_MODEL,
        "strengthen_model": DEFAULT_LIVE_MODEL,
        "finalization_model": s.finalization_model,
        "learning_model": s.learning_model,
        "mode": "balanced",
        "auto_suggestions_enabled": True,
        "suggestion_structured_enabled": s.suggestion_structured_enabled,
        "document_context_enabled": True,
        "knowledge_context_enabled": True,
        "previous_meetings_context_enabled": s.previous_meetings_context_enabled,
        "finalization_enabled": s.meeting_finalization_enabled,
        "learning_extraction_enabled": s.learning_extraction_enabled,
        "conversation_tree_enabled": True,
        "max_auto_cards": s.suggestion_max_cards_auto,
        "max_manual_cards": s.suggestion_max_cards_manual,
        "auto_suggestion_min_interval_seconds": 30,
        "document_context_max_chunks": s.document_context_max_chunks,
        "document_context_max_chars": s.document_context_max_chars,
        "previous_context_max_meetings": s.previous_meetings_context_max_meetings,
        "previous_context_max_chars": s.previous_meetings_context_max_chars,
        "knowledge_context_max_items": 12,
        "profile_id": None,
        "settings_json": {},
    }


def apply_mode_defaults(profile: AISettingsProfile) -> None:
    """Проставить лимиты/карточки профиля по его режиму (перезаписывает; вызывать до явных override)."""
    md = MODE_DEFAULTS.get(profile.suggestion_mode or "balanced", MODE_DEFAULTS["balanced"])
    for key, value in md.items():
        setattr(profile, key, value)


def profile_to_normalized(profile: AISettingsProfile) -> dict:
    norm = config_baseline()
    norm.update({
        "mode": profile.suggestion_mode or "balanced",
        "stt_provider": profile.stt_provider or norm["stt_provider"],
        "stt_model": profile.stt_model,
        "llm_provider": profile.llm_provider or norm["llm_provider"],
        "live_suggestion_model": profile.live_suggestion_model or norm["live_suggestion_model"],
        "strengthen_model": profile.strengthen_model or profile.live_suggestion_model or norm["strengthen_model"],
        "finalization_model": profile.finalization_model or norm["finalization_model"],
        "learning_model": profile.learning_model or norm["learning_model"],
        "auto_suggestions_enabled": profile.auto_suggestions_enabled,
        "suggestion_structured_enabled": profile.suggestion_structured_enabled,
        "document_context_enabled": profile.document_context_enabled,
        "knowledge_context_enabled": profile.knowledge_context_enabled,
        "previous_meetings_context_enabled": profile.previous_meetings_context_enabled,
        "finalization_enabled": profile.finalization_enabled,
        "learning_extraction_enabled": profile.learning_extraction_enabled,
        "conversation_tree_enabled": profile.conversation_tree_enabled,
        "max_auto_cards": profile.max_auto_cards,
        "max_manual_cards": profile.max_manual_cards,
        "auto_suggestion_min_interval_seconds": profile.auto_suggestion_min_interval_seconds,
        "document_context_max_chunks": profile.document_context_max_chunks or norm["document_context_max_chunks"],
        "document_context_max_chars": profile.document_context_max_chars or norm["document_context_max_chars"],
        "previous_context_max_meetings": profile.previous_context_max_meetings or norm["previous_context_max_meetings"],
        "previous_context_max_chars": profile.previous_context_max_chars or norm["previous_context_max_chars"],
        "knowledge_context_max_items": profile.knowledge_context_max_items or norm["knowledge_context_max_items"],
        "profile_id": profile.id,
        "settings_json": json.loads(profile.settings_json) if profile.settings_json else {},
    })
    return norm


# --- профили ---

async def get_default_profile(db: AsyncSession, user_id: int) -> AISettingsProfile | None:
    return (await db.execute(
        select(AISettingsProfile).where(
            AISettingsProfile.owner_user_id == user_id,
            AISettingsProfile.is_default == True,  # noqa: E712
        ).limit(1)
    )).scalar_one_or_none()


async def get_or_create_default_profile(db: AsyncSession, user_id: int) -> AISettingsProfile:
    """Вернуть default-профиль; если нет — создать из config (+ legacy UserSettings). Коммитит вызывающий."""
    existing = await get_default_profile(db, user_id)
    if existing:
        return existing
    # seed из legacy UserSettings (для совместимости со старым выбором модели/STT)
    from ..models.settings import UserSettings
    us = (await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))).scalar_one_or_none()
    profile = AISettingsProfile(
        owner_user_id=user_id, name="По умолчанию", profile_type="user", is_default=True,
        suggestion_mode="balanced", created_by_user_id=user_id,
        stt_provider=(us.stt_provider if us else None),
        live_suggestion_model=(us.llm_model if us else None),
    )
    apply_mode_defaults(profile)
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


async def list_profiles(db: AsyncSession, user_id: int) -> list[AISettingsProfile]:
    return list((await db.execute(
        select(AISettingsProfile).where(AISettingsProfile.owner_user_id == user_id)
        .order_by(AISettingsProfile.is_default.desc(), AISettingsProfile.created_at.asc())
    )).scalars().all())


async def make_default(db: AsyncSession, profile: AISettingsProfile) -> None:
    """Сделать профиль default, снять флаг с остальных профилей владельца."""
    others = (await db.execute(
        select(AISettingsProfile).where(
            AISettingsProfile.owner_user_id == profile.owner_user_id,
            AISettingsProfile.is_default == True,  # noqa: E712
            AISettingsProfile.id != profile.id,
        )
    )).scalars().all()
    for o in others:
        o.is_default = False
    profile.is_default = True
    await db.flush()


# --- резолвинг по встрече ---

async def resolve_for_meeting(db: AsyncSession, meeting_id: int) -> dict:
    """Нормализованные настройки встречи: snapshot > профиль встречи > default > config."""
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return config_baseline()
    if meeting.ai_settings_snapshot_json:
        try:
            snap = json.loads(meeting.ai_settings_snapshot_json)
            if isinstance(snap, dict):
                base = config_baseline()
                base.update(snap)  # снапшот поверх baseline (защита от отсутствующих ключей)
                return base
        except (ValueError, TypeError):
            pass
    if meeting.ai_settings_profile_id:
        prof = await db.get(AISettingsProfile, meeting.ai_settings_profile_id)
        if prof:
            return profile_to_normalized(prof)
    owner = meeting.created_by_user_id or meeting.user_id
    default = await get_default_profile(db, owner)
    if default:
        return profile_to_normalized(default)
    return config_baseline()


async def snapshot_for_meeting(db: AsyncSession, meeting_id: int) -> dict:
    """Заморозить настройки встречи (если ещё не заморожены). Коммитит вызывающий."""
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return config_baseline()
    if meeting.ai_settings_snapshot_json:
        return await resolve_for_meeting(db, meeting_id)
    # резолв из профиля/default/config (без snapshot) и заморозка
    if meeting.ai_settings_profile_id:
        prof = await db.get(AISettingsProfile, meeting.ai_settings_profile_id)
        resolved = profile_to_normalized(prof) if prof else config_baseline()
    else:
        owner = meeting.created_by_user_id or meeting.user_id
        default = await get_default_profile(db, owner)
        resolved = profile_to_normalized(default) if default else config_baseline()
    meeting.ai_settings_snapshot_json = json.dumps(resolved, ensure_ascii=False)
    return resolved


async def update_meeting_snapshot(db: AsyncSession, meeting_id: int, patch: dict) -> dict:
    """Применить patch к снапшоту встречи (валидируя). Коммитит вызывающий."""
    resolved = await resolve_for_meeting(db, meeting_id)
    clean = validate_patch(patch)
    resolved.update(clean)
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting:
        meeting.ai_settings_snapshot_json = json.dumps(resolved, ensure_ascii=False)
    return resolved


async def apply_profile_to_meeting(db: AsyncSession, meeting_id: int, profile: AISettingsProfile) -> dict:
    resolved = profile_to_normalized(profile)
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting:
        meeting.ai_settings_profile_id = profile.id
        meeting.ai_settings_snapshot_json = json.dumps(resolved, ensure_ascii=False)
    return resolved


# --- валидация ---

_BOOL_KEYS = {
    "auto_suggestions_enabled", "suggestion_structured_enabled", "document_context_enabled",
    "knowledge_context_enabled", "previous_meetings_context_enabled", "finalization_enabled",
    "learning_extraction_enabled",
}
_INT_KEYS = {
    "max_auto_cards", "max_manual_cards", "auto_suggestion_min_interval_seconds",
    "document_context_max_chunks", "document_context_max_chars",
    "previous_context_max_meetings", "previous_context_max_chars", "knowledge_context_max_items",
}
_MODEL_KEYS = {"live_suggestion_model", "strengthen_model", "finalization_model", "learning_model", "stt_model"}


def validate_patch(patch: dict) -> dict:
    """Очистить patch (только известные ключи, валидные значения). Бросает ValueError при грубых ошибках."""
    out: dict = {}
    if not isinstance(patch, dict):
        return out
    if "mode" in patch:
        if patch["mode"] not in MODES:
            raise ValueError("Неизвестный режим (mode)")
        out["mode"] = patch["mode"]
        out.update(MODE_DEFAULTS[patch["mode"]])  # режим задаёт лимиты
    if "stt_provider" in patch and patch["stt_provider"]:
        if patch["stt_provider"] not in STT_PROVIDERS:
            raise ValueError("Неизвестный STT-провайдер")
        out["stt_provider"] = patch["stt_provider"]
    if "llm_provider" in patch and patch["llm_provider"]:
        if patch["llm_provider"] not in LLM_PROVIDERS:
            raise ValueError("Неизвестный LLM-провайдер")
        out["llm_provider"] = patch["llm_provider"]
    for k in _MODEL_KEYS:
        if k in patch:
            if not valid_model_string(patch[k]):
                raise ValueError(f"Недопустимое имя модели: {k}")
            out[k] = patch[k] or None
    for k in _BOOL_KEYS:
        if k in patch and patch[k] is not None:
            out[k] = bool(patch[k])
    for k in _INT_KEYS:
        if k in patch and patch[k] is not None:
            out[k] = max(0, min(int(patch[k]), 100000))
    return out


def mode_tokens(mode: str, kind: str) -> int:
    return MODE_TOKENS.get(mode or "balanced", MODE_TOKENS["balanced"]).get(kind, 600)


def options_payload() -> dict:
    """Опции для UI. Без секретов."""
    return {
        "available_stt_providers": list(STT_PROVIDERS),
        "available_stt_models": {
            "deepgram": ["nova-2", "nova-3"],
            "elevenlabs": ["scribe_v1"],
            "gemini": ["gemini-live"],
        },
        "available_llm_providers": list(LLM_PROVIDERS),
        "available_llm_models": [
            "google/gemini-3-flash-preview", "google/gemini-3-pro-preview",
            "anthropic/claude-sonnet-4-6", "openai/gpt-5.1",
        ],
        "supported_modes": list(MODES),
        "defaults_from_config": config_baseline(),
        "feature_flags": {
            "suggestion_structured_enabled": get_settings().suggestion_structured_enabled,
            "meeting_finalization_enabled": get_settings().meeting_finalization_enabled,
            "learning_extraction_enabled": get_settings().learning_extraction_enabled,
            "previous_meetings_context_enabled": get_settings().previous_meetings_context_enabled,
        },
    }
