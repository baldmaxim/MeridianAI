"""Доступ к объектам, встречам и документам.

Модель «общей хронологии»: встречи/документы/объекты/заказчики больше не принадлежат
пользователю. Любой авторизованный сотрудник видит все встречи и документы и может с
ними работать (запись, удаление, управление). Поля user_id/owner_user_id/
created_by_user_id остаются только как информативная метка «автор».

Функции сохраняют прежние сигнатуры (вызываются из ~15 мест), но теперь разрешающие:
проверяют лишь существование сущности, а не принадлежность пользователю.
"""

from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Select

from ..models.meeting import MeetingSession
from ..models.directory import ProjectObject
from ..models.document import DocumentRecord


def accessible_object_ids_select(user_id: int) -> Select:
    """SELECT id всех объектов (общая модель — объекты видны всем)."""
    return select(ProjectObject.id.label("object_id"))


def accessible_meeting_filter(user_id: int):
    """Фильтр списков встреч: общая хронология — видны все встречи."""
    return true()


async def user_can_access_object(db: AsyncSession, user_id: int, object_id: int) -> bool:
    """True, если объект существует (объекты общие)."""
    return await db.get(ProjectObject, object_id) is not None


async def user_can_access_meeting(db: AsyncSession, user_id: int, meeting_id: int) -> bool:
    """True, если встреча существует (общая хронология)."""
    return await db.get(MeetingSession, meeting_id) is not None


# --- Право записи (стать active_audio_source) ---
#
# Разделение сохранено для совместимости вызовов: user_can_access_meeting → ПРОСМОТР;
# can_record_meeting → ЗАПИСЬ. В общей модели оба разрешены любому авторизованному.


async def user_object_access_level(db: AsyncSession, user_id: int, object_id: int) -> str | None:
    """Уровень доступа к объекту: manage, если объект существует, иначе None."""
    obj = await db.get(ProjectObject, object_id)
    return "manage" if obj is not None else None


async def can_record_meeting(db: AsyncSession, user_id: int, meeting_id: int) -> bool:
    """True, если встреча существует — записывать может любой авторизованный."""
    return await db.get(MeetingSession, meeting_id) is not None


# --- Доступ к документам ---


async def user_can_access_document(db: AsyncSession, user_id: int, document_id: int) -> bool:
    """True, если документ существует (документы общие)."""
    return await db.get(DocumentRecord, document_id) is not None


async def user_can_manage_document(db: AsyncSession, user_id: int, document_id: int) -> bool:
    """True, если документ существует — управлять может любой авторизованный."""
    return await db.get(DocumentRecord, document_id) is not None


async def current_user_meeting_role(db: AsyncSession, user_id: int, meeting_id: int) -> str:
    """Роль пользователя относительно встречи (для UI/live-state).

    Общая модель: автор → creator, остальные → object_manage (полный контроль в UI).
    """
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return "unknown"
    if meeting.created_by_user_id == user_id or meeting.user_id == user_id:
        return "creator"
    return "object_manage"
