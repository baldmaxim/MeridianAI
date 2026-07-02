"""Сервис persisted-ролей спикеров встречи (source of truth для дерева общения).

Диаризация v1 — две публичные стороны: «Мы» = self, «Не мы» = opponent.
Persisted-модель исторически может содержать ally/third_party (старые записи); новые
назначения сохраняются ТОЛЬКО как self/opponent. Чтение канонизирует legacy наружу:
ally→self, third_party→opponent. unknown/'' → очистка (удаление строки).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.meeting_conversation import MeetingSpeakerRole

logger = logging.getLogger("meridian.speaker_roles")

# Публичные стороны v1 (две). Сохраняем только их.
PUBLIC_SPEAKER_SIDES = ("self", "opponent")

# Алиасы входных значений → публичная сторона. Всё неизвестное → None (очистка).
_SIDE_ALIASES = {
    "self": "self", "our": "self", "ours": "self", "us": "self", "we": "self", "me": "self",
    "ally": "self",  # legacy → наша сторона
    "opponent": "opponent", "customer": "opponent", "client": "opponent",
    "them": "opponent", "they": "opponent", "other": "opponent",
    "not_us": "opponent", "not-we": "opponent", "not_we": "opponent",
    "third_party": "opponent", "third": "opponent",  # legacy → не мы
}


def to_public_side(side: str | None) -> str | None:
    """Свести любое значение/alias/legacy к публичной стороне (self|opponent) или None."""
    if not side:
        return None
    s = str(side).strip().lower()
    if s in ("", "unknown", "none", "clear"):
        return None
    return _SIDE_ALIASES.get(s)


def normalize_side(side: str | None) -> str | None:
    """Валидная публичная сторона (self|opponent) или None (очистить роль).

    Новые записи сохраняются только как self/opponent; ally→self, third_party→opponent.
    """
    return to_public_side(side)


async def get_roles_map(db: AsyncSession, meeting_id: int) -> dict[str, str]:
    """{speaker_label: public_side} — для MeetingRoom и rebuild дерева.

    Канонизирует legacy-значения из БД (ally→self, third_party→opponent). Битые/None
    стороны пропускаются.
    """
    rows = (await db.execute(
        select(MeetingSpeakerRole.speaker_label, MeetingSpeakerRole.side)
        .where(MeetingSpeakerRole.meeting_id == meeting_id)
    )).all()
    out: dict[str, str] = {}
    for label, side in rows:
        public = to_public_side(side)
        if public:
            out[label] = public
    return out


async def get_names_map(db: AsyncSession, meeting_id: int) -> dict[str, str]:
    """{speaker_label: display_name} — имена спикеров для live SessionManager и UI.

    Пустые/None display_name пропускаются.
    """
    rows = (await db.execute(
        select(MeetingSpeakerRole.speaker_label, MeetingSpeakerRole.display_name)
        .where(MeetingSpeakerRole.meeting_id == meeting_id)
    )).all()
    return {label: name for label, name in rows if (name or "").strip()}


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
    """Создать/обновить роль и/или имя спикера. Коммитит вызывающий.

    side=None/unknown → сторона очищается (но строка остаётся, если есть имя).
    display_name: None → имя не трогать; "" → очистить; иначе → задать.
    Строка удаляется, только когда не остаётся ни стороны, ни имени.
    """
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

    # целевое имя: None = не трогать; иначе нормализуем пустую строку к None
    touch_name = display_name is not None
    new_name = ((display_name or "").strip() or None) if touch_name else None
    effective_name = new_name if touch_name else (existing.display_name if existing else None)

    # ни стороны, ни имени → строка не нужна
    if norm is None and not effective_name:
        if existing:
            await db.delete(existing)
            await db.flush()
        return None

    if existing:
        existing.side = norm
        if touch_name:
            existing.display_name = new_name
        if assigned_by_user_id is not None:
            existing.assigned_by_user_id = assigned_by_user_id
        await db.flush()
        return existing

    role = MeetingSpeakerRole(
        meeting_id=meeting_id, speaker_label=label, side=norm,
        display_name=effective_name, assigned_by_user_id=assigned_by_user_id,
    )
    db.add(role)
    await db.flush()
    return role


# --- Speaker Identity Graph v1 compatibility (Этап 4) -----------------------
# Тонкий мост legacy self/opponent → новый внутренний граф. Существующий API/поля
# (PUBLIC_SPEAKER_SIDES, to_public_side, get_roles_map, ...) НЕ меняются.

def normalize_legacy_side(side: str | None) -> str:
    """legacy self/opponent/... → SpeakerSide (our_side/counterparty/third_party/unknown)."""
    from ..core.context.speaker_identity import normalize_side as _ns
    return _ns(side)


def to_speaker_identity_map(roles_map: dict[str, str] | None,
                            *, assigned: bool = True):
    """Свести {speaker_label: legacy_side} к SpeakerIdentityMap.

    assigned=True — это подтверждённые пользователем назначения → source=manual_correction;
    иначе трактуем как legacy_role. Имена/PII в граф не тянем (адресность по стороне/роли).
    """
    from .speaker_identity_service import SpeakerIdentityService
    svc = SpeakerIdentityService()
    if assigned:
        return svc.build_runtime_map(manual_overrides=roles_map or {})
    return svc.build_from_legacy_roles(roles_map or {})
