"""API AI-настроек (Этап 9): профили, options, настройки конкретной встречи.

Секреты (API keys) не возвращаются. Профили — per-owner (owner_user_id).
Изменение настроек встречи — creator/participant/edit/manage (как редактирование встречи).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.meeting import MeetingSession
from ..models.ai_settings import AISettingsProfile
from ..auth.dependencies import get_current_user
from ..services.page_access import require_page
from ..services.access import user_can_access_meeting, can_record_meeting
from ..services.meeting_room import room_registry
from ..services import ai_settings as ais
from ..schemas.ai_settings import (
    AISettingsProfileOut, AISettingsProfileCreate, AISettingsProfileUpdate,
    AISettingsResolved, MeetingAISettingsOut, MeetingAISettingsPatch,
)

logger = logging.getLogger("meridian.ai_settings")

router = APIRouter()          # /api/ai-settings
meeting_router = APIRouter()  # /api/meetings

# Управление профилями AI — страница "AI-профили" (§12). Чтение профилей/опций
# остаётся общим: нужно при выборе профиля в окне встречи (MeetingAISettings).
_require_ai = Depends(require_page("ai-settings"))


# --- профили ---

def _apply_payload(profile: AISettingsProfile, payload: dict) -> None:
    """Записать поля профиля из payload: режим → mode-defaults → явные override (с валидацией)."""
    mode = payload.get("suggestion_mode", profile.suggestion_mode or "balanced")
    if mode not in ais.MODES:
        raise HTTPException(422, "Неизвестный режим (mode)")
    profile.suggestion_mode = mode
    ais.apply_mode_defaults(profile)  # базовые лимиты по режиму
    for key, value in payload.items():
        if key == "suggestion_mode":
            continue
        if key in {"live_suggestion_model", "strengthen_model", "finalization_model", "learning_model", "stt_model"}:
            if not ais.valid_model_string(value):
                raise HTTPException(422, f"Недопустимое имя модели: {key}")
        if key == "stt_provider" and value and value not in ais.STT_PROVIDERS:
            raise HTTPException(422, "Неизвестный STT-провайдер")
        if key == "llm_provider" and value and value not in ais.LLM_PROVIDERS:
            raise HTTPException(422, "Неизвестный LLM-провайдер")
        setattr(profile, key, value)


@router.get("/options")
async def get_options(user: User = Depends(get_current_user)):
    return ais.options_payload()


@router.get("/profiles", response_model=list[AISettingsProfileOut])
async def list_profiles(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # гарантируем наличие default-профиля
    await ais.get_or_create_default_profile(db, user.id)
    return await ais.list_profiles(db, user.id)


@router.post("/profiles", response_model=AISettingsProfileOut, dependencies=[_require_ai])
async def create_profile(data: AISettingsProfileCreate, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    profile = AISettingsProfile(owner_user_id=user.id, name=data.name, profile_type="user",
                                created_by_user_id=user.id)
    _apply_payload(profile, data.model_dump(exclude_unset=True))
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


@router.get("/profiles/{profile_id}", response_model=AISettingsProfileOut)
async def get_profile(profile_id: int, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    p = await db.get(AISettingsProfile, profile_id)
    if not p or p.owner_user_id != user.id:
        raise HTTPException(404, "Профиль не найден")
    return p


@router.put("/profiles/{profile_id}", response_model=AISettingsProfileOut, dependencies=[_require_ai])
async def update_profile(profile_id: int, data: AISettingsProfileUpdate,
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(AISettingsProfile, profile_id)
    if not p or p.owner_user_id != user.id:
        raise HTTPException(404, "Профиль не найден")
    payload = data.model_dump(exclude_unset=True)
    if "name" in payload and payload["name"]:
        p.name = payload.pop("name")
    if "description" in payload:
        p.description = payload.pop("description")
    _apply_payload(p, payload)
    await db.flush()
    await db.refresh(p)
    return p


@router.delete("/profiles/{profile_id}", dependencies=[_require_ai])
async def delete_profile(profile_id: int, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    p = await db.get(AISettingsProfile, profile_id)
    if not p or p.owner_user_id != user.id:
        raise HTTPException(404, "Профиль не найден")
    if p.is_default:
        raise HTTPException(400, "Нельзя удалить профиль по умолчанию")
    await db.delete(p)
    await db.flush()
    return {"ok": True}


@router.post("/profiles/{profile_id}/make-default", response_model=AISettingsProfileOut, dependencies=[_require_ai])
async def make_default_profile(profile_id: int, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    p = await db.get(AISettingsProfile, profile_id)
    if not p or p.owner_user_id != user.id:
        raise HTTPException(404, "Профиль не найден")
    await ais.make_default(db, p)
    await db.refresh(p)
    return p


# --- настройки встречи ---

def _summary(resolved: dict) -> dict:
    return {
        "suggestion_mode": resolved.get("mode"),
        "auto_suggestions_enabled": resolved.get("auto_suggestions_enabled"),
        "document_context_enabled": resolved.get("document_context_enabled"),
        "knowledge_context_enabled": resolved.get("knowledge_context_enabled"),
        "previous_meetings_context_enabled": resolved.get("previous_meetings_context_enabled"),
    }


async def _apply_live(meeting_id: int, resolved: dict) -> None:
    """Применить настройки к live-комнате (если есть) и разослать событие."""
    room = room_registry.get_room(meeting_id)
    if room:
        try:
            room.session.set_ai_settings(resolved)
            await room.broadcast({"type": "ai_settings_updated", "meeting_id": meeting_id,
                                  "settings_summary": _summary(resolved)})
        except Exception:
            pass


@meeting_router.get("/{meeting_id}/ai-settings", response_model=MeetingAISettingsOut)
async def get_meeting_ai_settings(meeting_id: int, user: User = Depends(get_current_user),
                                  db: AsyncSession = Depends(get_db)):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Встреча не найдена")
    if not await user_can_access_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")
    resolved = await ais.resolve_for_meeting(db, meeting_id)
    can_edit = await can_record_meeting(db, user.id, meeting_id)
    return MeetingAISettingsOut(
        meeting_id=meeting_id, profile_id=meeting.ai_settings_profile_id,
        resolved=AISettingsResolved(**{k: resolved.get(k) for k in AISettingsResolved.model_fields}),
        has_snapshot=bool(meeting.ai_settings_snapshot_json), can_edit=can_edit,
    )


@meeting_router.patch("/{meeting_id}/ai-settings", response_model=MeetingAISettingsOut)
async def patch_meeting_ai_settings(meeting_id: int, patch: MeetingAISettingsPatch,
                                    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Встреча не найдена")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения настроек встречи")
    patch_dict = patch.model_dump(exclude_unset=True)
    # Канареечное включение Signal Engine — логируем ТОЛЬКО имена ключей (без значений и текста).
    signal_keys = sorted(k for k in patch_dict if k.startswith("signal_engine_"))
    if signal_keys:
        logger.info("[SignalCanary] meeting_id=%s user_id=%s changed_keys=%s",
                    meeting_id, user.id, signal_keys)
    # Source Reconciliation canary (Этап 11): логируем только имена ключей (без значений)
    reconcile_keys = sorted(k for k in patch_dict if k.startswith("source_reconcile_"))
    if reconcile_keys:
        logger.info("[SourceReconcileCanary] meeting_id=%s user_id=%s changed_keys=%s",
                    meeting_id, user.id, reconcile_keys)
    # Per-channel STT canary (Этап 17): логируем только имена ключей (без значений)
    stt_keys = sorted(k for k in patch_dict if k.startswith("audio_per_channel_stt_"))
    if stt_keys:
        logger.info("[AudioPerChannelSttCanary] meeting_id=%s user_id=%s changed_keys=%s",
                    meeting_id, user.id, stt_keys)
    # Per-channel STT provider canary (Этап 18): только имена ключей (без provider/model/language значений)
    _stt_provider_suffixes = (
        "provider", "timeout_seconds", "language_code", "model_id", "cache_enabled",
        "cache_max_entries", "max_audio_seconds", "max_wav_bytes",
        "max_provider_calls_per_meeting", "max_provider_audio_seconds_per_meeting")
    stt_provider_keys = sorted(
        k for k in stt_keys if k.removeprefix("audio_per_channel_stt_") in _stt_provider_suffixes)
    if stt_provider_keys:
        logger.info("[AudioPerChannelSttProviderCanary] meeting_id=%s user_id=%s changed_keys=%s",
                    meeting_id, user.id, stt_provider_keys)
    # Speaker Identity Hints (Этап 5): логируем только группы (без labels/значений/имён)
    if "speaker_identity_hints" in patch_dict:
        sih = patch_dict["speaker_identity_hints"]
        cleared = sih is None
        groups = sorted(k for k in (sih or {})
                        if k in ("speaker_labels", "stable_ids", "audio_sources", "channel_labels"))
        logger.info("[SpeakerIdentityHints] meeting_id=%s user_id=%s changed=true cleared=%s groups=%s",
                    meeting_id, user.id, cleared, groups)
    try:
        resolved = await ais.update_meeting_snapshot(db, meeting_id, patch_dict)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await db.flush()
    await _apply_live(meeting_id, resolved)
    return MeetingAISettingsOut(
        meeting_id=meeting_id, profile_id=meeting.ai_settings_profile_id,
        resolved=AISettingsResolved(**{k: resolved.get(k) for k in AISettingsResolved.model_fields}),
        has_snapshot=True, can_edit=True,
    )


@meeting_router.post("/{meeting_id}/ai-settings/apply-profile/{profile_id}", response_model=MeetingAISettingsOut)
async def apply_profile(meeting_id: int, profile_id: int, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    meeting = await db.get(MeetingSession, meeting_id)
    if not meeting:
        raise HTTPException(404, "Встреча не найдена")
    if not await can_record_meeting(db, user.id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для изменения настроек встречи")
    profile = await db.get(AISettingsProfile, profile_id)
    if not profile or profile.owner_user_id != user.id:
        raise HTTPException(404, "Профиль не найден")
    resolved = await ais.apply_profile_to_meeting(db, meeting_id, profile)
    await db.flush()
    await _apply_live(meeting_id, resolved)
    return MeetingAISettingsOut(
        meeting_id=meeting_id, profile_id=profile_id,
        resolved=AISettingsResolved(**{k: resolved.get(k) for k in AISettingsResolved.model_fields}),
        has_snapshot=True, can_edit=True,
    )
