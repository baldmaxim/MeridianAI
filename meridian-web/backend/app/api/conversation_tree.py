"""API дерева общения встречи (Conversation Tree).

Просмотр — user_can_access_meeting. Изменение (PATCH/merge/rebuild/refine) — can_record_meeting
(creator/participant/edit/manage). View-only/object_view редактировать не могут.
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..auth.dependencies import get_current_user
from ..services.access import user_can_access_meeting, can_record_meeting
from ..services.conversation_tree import ConversationTreeService
from ..services.meeting_room import room_registry
from ..schemas.conversation_tree import (
    ConversationTreeOut, ConversationTopicOut, ConversationTopicUpdate,
)

logger = logging.getLogger("meridian.conversation_tree.api")

router = APIRouter()
_service = ConversationTreeService()

# простейший троттлинг ручного LLM-refine: meeting_id -> last ts
_REFINE_MIN_INTERVAL = 20.0
_last_refine: dict[int, float] = {}


class MergeRequest(BaseModel):
    target_id: int


async def _require_access(db: AsyncSession, user_id: int, meeting_id: int) -> None:
    if not await user_can_access_meeting(db, user_id, meeting_id):
        raise HTTPException(403, "Нет доступа к встрече")


async def _require_edit(db: AsyncSession, user_id: int, meeting_id: int) -> None:
    if not await can_record_meeting(db, user_id, meeting_id):
        raise HTTPException(403, "Недостаточно прав для редактирования")


async def _notify_topic(meeting_id: int, topic: ConversationTopicOut) -> None:
    room = room_registry.get_room(meeting_id)
    if room:
        try:
            room._tree_version += 1
            await room.broadcast({
                "type": "conversation_tree_updated",
                "meeting_id": meeting_id,
                "topic": topic.model_dump(mode="json"),
                "tree_version": room._tree_version,
            })
        except Exception:
            pass


@router.get("/{meeting_id}/conversation-tree", response_model=ConversationTreeOut)
async def get_conversation_tree(meeting_id: int, user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    await _require_access(db, user.id, meeting_id)
    return await _service.get_tree(db, meeting_id)


@router.patch("/{meeting_id}/conversation-tree/{topic_id}", response_model=ConversationTopicOut)
async def patch_conversation_topic(meeting_id: int, topic_id: int, patch: ConversationTopicUpdate,
                                   user: User = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    await _require_access(db, user.id, meeting_id)
    await _require_edit(db, user.id, meeting_id)
    topic = await _service.manual_update_topic(db, meeting_id, topic_id, patch)
    if topic is None:
        raise HTTPException(404, "Тема не найдена")
    await db.commit()
    await _notify_topic(meeting_id, topic)
    return topic


@router.post("/{meeting_id}/conversation-tree/{topic_id}/merge", response_model=ConversationTopicOut)
async def merge_conversation_topic(meeting_id: int, topic_id: int, body: MergeRequest,
                                   user: User = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    await _require_access(db, user.id, meeting_id)
    await _require_edit(db, user.id, meeting_id)
    topic = await _service.merge_topics(db, meeting_id, source_id=topic_id, target_id=body.target_id)
    if topic is None:
        raise HTTPException(400, "Не удалось слить темы (проверьте id)")
    await db.commit()
    await _notify_topic(meeting_id, topic)
    return topic


async def _build_llm_client(db: AsyncSession, meeting_id: int):
    """LLM-клиент для offline-пересборки/уточнения (OpenRouter). None — нет ключа/ошибка."""
    try:
        from ..services.api_keys import load_api_keys
        from ..services.ai_settings import resolve_for_meeting
        from ..config import get_settings
        from ..core.llm.client import LLMClient

        api_keys = await load_api_keys()
        key = api_keys.get("openrouter")
        if not key:
            return None
        resolved = await resolve_for_meeting(db, meeting_id)
        model = resolved.get("live_suggestion_model") or get_settings().finalization_model
        return LLMClient(api_key=key, model=model, temperature=0.2, max_tokens=1400)
    except Exception as e:
        logger.warning("conversation-tree: meeting %s client init failed: %s", meeting_id, str(e)[:120])
        return None


@router.post("/{meeting_id}/conversation-tree/rebuild", response_model=ConversationTreeOut)
async def rebuild_conversation_tree(meeting_id: int, user: User = Depends(get_current_user),
                                    db: AsyncSession = Depends(get_db)):
    await _require_access(db, user.id, meeting_id)
    await _require_edit(db, user.id, meeting_id)
    # persisted-роли (source of truth) + перекрытие live-комнатой, если она открыта
    from ..services.speaker_roles import get_roles_map
    roles = await get_roles_map(db, meeting_id)
    room = room_registry.get_room(meeting_id)
    if room:
        roles.update(room.session.speaker_roles)
    llm_client = await _build_llm_client(db, meeting_id)
    # есть ключ → LLM-пересборка осмысленных условий; нет → детерминированный fallback
    tree = await _service.rebuild_with_llm(db, meeting_id, llm_client, speaker_roles=roles)
    await db.commit()
    return tree


@router.post("/{meeting_id}/conversation-tree/refine", response_model=ConversationTreeOut)
async def refine_conversation_tree(meeting_id: int, user: User = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)):
    await _require_access(db, user.id, meeting_id)
    await _require_edit(db, user.id, meeting_id)

    now = time.time()
    last = _last_refine.get(meeting_id, 0.0)
    if now - last < _REFINE_MIN_INTERVAL:
        raise HTTPException(429, "Слишком часто. Повторите чуть позже.")
    _last_refine[meeting_id] = now

    # live-комната с ключом → форсировать немедленную LLM-экстракцию по свежему диалогу
    room = room_registry.get_room(meeting_id)
    if room is not None and room.session.llm_client is not None:
        try:
            room._tree_dirty = True
            await room._flush_tree_extraction()
        except Exception as e:
            logger.warning("refine: meeting %s live flush failed: %s", meeting_id, str(e)[:120])
        return await _service.get_tree(db, meeting_id)

    # offline → собрать клиент и пересобрать дерево через LLM по persisted-транскрипту
    llm_client = await _build_llm_client(db, meeting_id)
    tree = await _service.rebuild_with_llm(db, meeting_id, llm_client)
    await db.commit()
    return tree
