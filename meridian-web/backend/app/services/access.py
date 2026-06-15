"""Сервис проверки доступа сотрудников к объектам и встречам (Этап 1 MVP).

Правила доступа к объекту:
  - пользователь — владелец/создатель объекта (owner_user_id);
  - объект назначен пользователю напрямую (grant grantee_type='user');
  - объект назначен одному из отделов пользователя (grant grantee_type='department').

Правила доступа к встрече:
  - пользователь создал встречу (created_by_user_id или legacy user_id);
  - пользователь — участник встречи (meeting_participants);
  - у встречи есть object_id и есть доступ к этому объекту.
"""

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Select

from ..models.meeting import MeetingSession, MeetingDocumentRecord
from ..models.directory import (
    ProjectObject,
    UserDepartment,
    ObjectAccessGrant,
    MeetingParticipant,
)
from ..models.document import DocumentRecord


def accessible_object_ids_select(user_id: int) -> Select:
    """SELECT id объектов, к которым у пользователя есть доступ (для in_-фильтров)."""
    owner = select(ProjectObject.id.label("object_id")).where(
        ProjectObject.owner_user_id == user_id
    )
    direct = select(ObjectAccessGrant.object_id.label("object_id")).where(
        ObjectAccessGrant.grantee_type == "user",
        ObjectAccessGrant.grantee_user_id == user_id,
    )
    dept = (
        select(ObjectAccessGrant.object_id.label("object_id"))
        .join(
            UserDepartment,
            UserDepartment.department_id == ObjectAccessGrant.grantee_department_id,
        )
        .where(
            ObjectAccessGrant.grantee_type == "department",
            UserDepartment.user_id == user_id,
        )
    )
    return owner.union(direct, dept)


def accessible_meeting_filter(user_id: int):
    """OR-условие для списков встреч: создатель ∪ участник ∪ доступ к объекту."""
    participant_ids = select(MeetingParticipant.meeting_id).where(
        MeetingParticipant.user_id == user_id
    )
    obj_ids = accessible_object_ids_select(user_id)
    return or_(
        MeetingSession.user_id == user_id,
        MeetingSession.created_by_user_id == user_id,
        MeetingSession.id.in_(participant_ids),
        and_(
            MeetingSession.object_id.isnot(None),
            MeetingSession.object_id.in_(obj_ids),
        ),
    )


async def user_can_access_object(db: AsyncSession, user_id: int, object_id: int) -> bool:
    """True, если пользователь владелец объекта, или объект выдан ему/его отделу."""
    obj = await db.get(ProjectObject, object_id)
    if obj is None:
        return False
    if obj.owner_user_id == user_id:
        return True

    direct = await db.execute(
        select(ObjectAccessGrant.id)
        .where(
            ObjectAccessGrant.object_id == object_id,
            ObjectAccessGrant.grantee_type == "user",
            ObjectAccessGrant.grantee_user_id == user_id,
        )
        .limit(1)
    )
    if direct.first() is not None:
        return True

    dept = await db.execute(
        select(ObjectAccessGrant.id)
        .join(
            UserDepartment,
            UserDepartment.department_id == ObjectAccessGrant.grantee_department_id,
        )
        .where(
            ObjectAccessGrant.object_id == object_id,
            ObjectAccessGrant.grantee_type == "department",
            UserDepartment.user_id == user_id,
        )
        .limit(1)
    )
    return dept.first() is not None


async def user_can_access_meeting(db: AsyncSession, user_id: int, meeting_id: int) -> bool:
    """True, если пользователь создал встречу, участник, или имеет доступ к её объекту."""
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return False
    if meeting.user_id == user_id or meeting.created_by_user_id == user_id:
        return True

    part = await db.execute(
        select(MeetingParticipant.id)
        .where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == user_id,
        )
        .limit(1)
    )
    if part.first() is not None:
        return True

    if meeting.object_id is not None:
        return await user_can_access_object(db, user_id, meeting.object_id)
    return False


# --- Этап 3: право записи (стать active_audio_source) ---
#
# Разделение: user_can_access_meeting → ПРОСМОТР; can_record_meeting → ЗАПИСЬ.

_LEVEL_ORDER = {"view": 1, "edit": 2, "manage": 3}


async def user_object_access_level(db: AsyncSession, user_id: int, object_id: int) -> str | None:
    """Наивысший уровень доступа пользователя к объекту: manage | edit | view | None.

    Владелец объекта трактуется как manage. Учитываются прямые и отделовские гранты.
    """
    obj = await db.get(ProjectObject, object_id)
    if obj is None:
        return None
    if obj.owner_user_id == user_id:
        return "manage"

    levels: list[str] = []
    direct = await db.execute(
        select(ObjectAccessGrant.access_level).where(
            ObjectAccessGrant.object_id == object_id,
            ObjectAccessGrant.grantee_type == "user",
            ObjectAccessGrant.grantee_user_id == user_id,
        )
    )
    levels += list(direct.scalars().all())
    dept = await db.execute(
        select(ObjectAccessGrant.access_level)
        .join(
            UserDepartment,
            UserDepartment.department_id == ObjectAccessGrant.grantee_department_id,
        )
        .where(
            ObjectAccessGrant.object_id == object_id,
            ObjectAccessGrant.grantee_type == "department",
            UserDepartment.user_id == user_id,
        )
    )
    levels += list(dept.scalars().all())
    if not levels:
        return None
    return max(levels, key=lambda lv: _LEVEL_ORDER.get(lv, 0))


async def _participant_role(db: AsyncSession, user_id: int, meeting_id: int) -> str | None:
    r = await db.execute(
        select(MeetingParticipant.role)
        .where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == user_id,
        )
        .limit(1)
    )
    return r.scalar_one_or_none()


async def can_record_meeting(db: AsyncSession, user_id: int, meeting_id: int) -> bool:
    """True, если пользователь имеет право запускать запись (стать источником аудио).

    Правила MVP:
      - создатель встречи (created_by_user_id / legacy user_id);
      - участник с role owner/participant (viewer — нет);
      - доступ к объекту встречи уровня edit/manage (view — только просмотр);
      - нет object_id → только создатель/участник.
    """
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return False
    if meeting.created_by_user_id == user_id or meeting.user_id == user_id:
        return True
    role = await _participant_role(db, user_id, meeting_id)
    if role in ("owner", "participant"):
        return True
    if meeting.object_id is not None:
        level = await user_object_access_level(db, user_id, meeting.object_id)
        if level in ("edit", "manage"):
            return True
    return False


# --- Этап 4: доступ к документам ---


async def user_can_access_document(db: AsyncSession, user_id: int, document_id: int) -> bool:
    """Видеть документ: создатель, доступ к его объекту, или он прикреплён к доступной встрече."""
    doc = await db.get(DocumentRecord, document_id)
    if doc is None:
        return False
    if doc.created_by_user_id == user_id or doc.owner_user_id == user_id:
        return True
    if doc.object_id is not None and await user_can_access_object(db, user_id, doc.object_id):
        return True
    # прикреплён к встрече, к которой есть доступ
    rows = await db.execute(
        select(MeetingDocumentRecord.session_id)
        .where(MeetingDocumentRecord.document_id == document_id)
        .limit(20)
    )
    for (session_id,) in rows.all():
        if await user_can_access_meeting(db, user_id, session_id):
            return True
    return False


async def user_can_manage_document(db: AsyncSession, user_id: int, document_id: int) -> bool:
    """Удалять/редактировать документ: создатель или manage-доступ к его объекту."""
    doc = await db.get(DocumentRecord, document_id)
    if doc is None:
        return False
    if doc.created_by_user_id == user_id or doc.owner_user_id == user_id:
        return True
    if doc.object_id is not None:
        level = await user_object_access_level(db, user_id, doc.object_id)
        if level == "manage":
            return True
    return False


async def current_user_meeting_role(db: AsyncSession, user_id: int, meeting_id: int) -> str:
    """Роль пользователя относительно встречи (для UI/live-state).

    creator | participant | viewer | object_view | object_edit | object_manage | unknown
    """
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return "unknown"
    if meeting.created_by_user_id == user_id or meeting.user_id == user_id:
        return "creator"
    role = await _participant_role(db, user_id, meeting_id)
    if role in ("owner", "participant"):
        return "participant"
    if role == "viewer":
        return "viewer"
    if meeting.object_id is not None:
        level = await user_object_access_level(db, user_id, meeting.object_id)
        if level == "manage":
            return "object_manage"
        if level == "edit":
            return "object_edit"
        if level == "view":
            return "object_view"
    return "unknown"
