"""Сервис persisted-ролей спикеров встречи (source of truth для дерева общения).

Словарь сторон — live (self/opponent/ally/third_party). Нормализуем синонимы из API:
our→self, customer/client→opponent, unknown/'' → очистка (удаление строки).
"""

import logging

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.meeting_conversation import MeetingSpeakerRole, SPEAKER_SIDES

logger = logging.getLogger("meridian.speaker_roles")

# нормализация входных значений стороны к live-словарю; None → очистить
_SIDE_ALIASES = {
    "self": "self", "our": "self", "us": "self", "we": "self",
    "opponent": "opponent", "customer": "opponent", "client": "opponent",
    "ally": "ally",
    "third_party": "third_party", "third": "third_party",
}


def normalize_side(side: str | None) -> str | None:
    """Вернуть валидную live-сторону или None (очистить роль)."""
    if not side:
        return None
    s = str(side).strip().lower()
    if s in ("unknown", "none", "clear", ""):
        return None
    return _SIDE_ALIASES.get(s, s if s in SPEAKER_SIDES else None)


async def get_roles_map(db: AsyncSession, meeting_id: int) -> dict[str, str]:
    """{speaker_label: side} — для загрузки в MeetingRoom и rebuild дерева."""
    rows = (await db.execute(
        select(MeetingSpeakerRole.speaker_label, MeetingSpeakerRole.side)
        .where(MeetingSpeakerRole.meeting_id == meeting_id)
    )).all()
    return {label: side for label, side in rows}


async def list_roles(db: AsyncSession, meeting_id: int) -> list[MeetingSpeakerRole]:
    return list((await db.execute(
        select(MeetingSpeakerRole)
        .where(MeetingSpeakerRole.meeting_id == meeting_id)
        .order_by(MeetingSpeakerRole.speaker_label.asc())
    )).scalars().all())


async def upsert_role(
    db: AsyncSession, meeting_id: int, speaker_label: str, *,
    side: str | None, display_name: str | None = None, assigned_by_user_id: int | None = None,
) -> MeetingSpeakerRole | None:
    """Создать/обновить роль. side=None/unknown → удалить строку (вернёт None). Коммитит вызывающий."""
    label = (speaker_label or "").strip()
    if not label:
        return None
    norm = normalize_side(side)
    existing = (await db.execute(
        select(MeetingSpeakerRole).where(
            MeetingSpeakerRole.meeting_id == meeting_id,
            MeetingSpeakerRole.speaker_label == label,
        )
    )).scalar_one_or_none()

    if norm is None:
        if existing:
            await db.delete(existing)
            await db.flush()
        return None

    if existing:
        existing.side = norm
        if display_name is not None:
            existing.display_name = display_name or None
        if assigned_by_user_id is not None:
            existing.assigned_by_user_id = assigned_by_user_id
        await db.flush()
        return existing

    role = MeetingSpeakerRole(
        meeting_id=meeting_id, speaker_label=label, side=norm,
        display_name=(display_name or None), assigned_by_user_id=assigned_by_user_id,
    )
    db.add(role)
    await db.flush()
    return role
