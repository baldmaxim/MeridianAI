"""Доступ к объектам, встречам, документам и RAG-папкам.

Модель «ручной выдачи доступа к проектам»:
- has_all(user) = роль admin ИЛИ users.all_objects_access — видит всё.
- Объект виден: has_all ИЛИ грант user_object_access ИЛИ грант user_customer_access
  на заказчика объекта.
- Встреча / документ / RAG-папка: object_id задан → доступ строго по объекту (авторство
  доступа НЕ даёт); object_id IS NULL → has_all или автор.

Функции сохраняют прежние сигнатуры (вызываются из десятков мест). Условия для списков
(`*_filter`, `*_select`) — чистый SQL без await; user_id=None (автор удалён, фоновые задачи)
всегда означает «нет доступа».
"""

from sqlalchemy import and_, exists, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.selectable import Select

from ..models.meeting import MeetingSession
from ..models.directory import Customer, ProjectObject
from ..models.document import DocumentRecord
from ..models.object_access import UserCustomerAccess, UserObjectAccess
from ..models.rag import RagFolder
from ..models.user import User


def _has_all_clause(user_id: int | None):
    """SQL-условие «пользователь видит всё» (админ или флаг all_objects_access)."""
    if user_id is None:
        return false()
    return exists(
        select(User.id).where(
            User.id == user_id,
            or_(User.role == "admin", User.all_objects_access.is_(True)),
        )
    )


def _object_visible_clause(user_id: int | None, object_id_col, customer_id_col):
    """Объект виден: has_all ИЛИ грант объекта ИЛИ грант заказчика."""
    if user_id is None:
        return false()
    return or_(
        _has_all_clause(user_id),
        exists(
            select(UserObjectAccess.user_id).where(
                UserObjectAccess.user_id == user_id,
                UserObjectAccess.object_id == object_id_col,
            )
        ),
        exists(
            select(UserCustomerAccess.user_id).where(
                UserCustomerAccess.user_id == user_id,
                UserCustomerAccess.customer_id == customer_id_col,
            )
        ),
    )


def accessible_object_ids_select(user_id: int | None) -> Select:
    """SELECT id (label object_id) объектов, видимых пользователю."""
    po = aliased(ProjectObject)
    return select(po.id.label("object_id")).where(
        _object_visible_clause(user_id, po.id, po.customer_id)
    )


def accessible_customer_ids_select(user_id: int | None) -> Select:
    """SELECT id (label customer_id) заказчиков: has_all, грант заказчика или видимый объект."""
    c = aliased(Customer)
    po = aliased(ProjectObject)
    if user_id is None:
        return select(c.id.label("customer_id")).where(false())
    return select(c.id.label("customer_id")).where(
        or_(
            _has_all_clause(user_id),
            exists(
                select(UserCustomerAccess.user_id).where(
                    UserCustomerAccess.user_id == user_id,
                    UserCustomerAccess.customer_id == c.id,
                )
            ),
            exists(
                select(po.id).where(
                    po.customer_id == c.id,
                    _object_visible_clause(user_id, po.id, po.customer_id),
                )
            ),
        )
    )


def _scoped_filter(user_id: int | None, object_id_col, *author_cols):
    """Общее условие для сущностей с object_id: по объекту, а без объекта — has_all/автор."""
    if user_id is None:
        return false()
    return or_(
        _has_all_clause(user_id),
        and_(object_id_col.is_not(None), object_id_col.in_(accessible_object_ids_select(user_id))),
        and_(object_id_col.is_(None), or_(*[col == user_id for col in author_cols])),
    )


def accessible_meeting_filter(user_id: int | None):
    """Фильтр списков встреч."""
    return _scoped_filter(
        user_id, MeetingSession.object_id, MeetingSession.user_id, MeetingSession.created_by_user_id
    )


def document_filter(user_id: int | None):
    """Фильтр списков документов."""
    return _scoped_filter(
        user_id, DocumentRecord.object_id,
        DocumentRecord.owner_user_id, DocumentRecord.created_by_user_id,
    )


def rag_folder_filter(user_id: int | None):
    """Фильтр списков RAG-папок."""
    return _scoped_filter(
        user_id, RagFolder.object_id, RagFolder.owner_user_id, RagFolder.created_by_user_id
    )


async def user_has_all_objects(db: AsyncSession, user_id: int | None) -> bool:
    """True, если пользователь — админ или имеет флаг «все проекты»."""
    if user_id is None:
        return False
    return bool(await db.scalar(select(_has_all_clause(user_id))))


async def user_can_access_object(db: AsyncSession, user_id: int | None, object_id: int) -> bool:
    """True, если объект существует и виден пользователю."""
    return (
        await db.scalar(
            select(ProjectObject.id).where(
                ProjectObject.id == object_id,
                ProjectObject.id.in_(accessible_object_ids_select(user_id)),
            )
        )
    ) is not None


async def user_can_access_customer(db: AsyncSession, user_id: int | None, customer_id: int) -> bool:
    """True, если заказчик существует и виден пользователю (has_all, грант или видимый объект)."""
    return (
        await db.scalar(
            select(Customer.id).where(
                Customer.id == customer_id,
                Customer.id.in_(accessible_customer_ids_select(user_id)),
            )
        )
    ) is not None


async def user_can_access_meeting(db: AsyncSession, user_id: int | None, meeting_id: int) -> bool:
    """True, если встреча существует и доступна пользователю."""
    return (
        await db.scalar(
            select(MeetingSession.id).where(
                MeetingSession.id == meeting_id, accessible_meeting_filter(user_id)
            )
        )
    ) is not None


# --- Право записи (стать active_audio_source) ---
#
# Разделение сохранено для совместимости вызовов: user_can_access_meeting → ПРОСМОТР;
# can_record_meeting → ЗАПИСЬ. Правила одинаковы: доступ к встрече = право записи.


async def user_object_access_level(db: AsyncSession, user_id: int | None, object_id: int) -> str | None:
    """Уровень доступа к объекту: manage, если объект виден, иначе None."""
    return "manage" if await user_can_access_object(db, user_id, object_id) else None


async def can_record_meeting(db: AsyncSession, user_id: int | None, meeting_id: int) -> bool:
    """True, если встреча доступна пользователю (просмотр = запись)."""
    return await user_can_access_meeting(db, user_id, meeting_id)


# --- Доступ к документам ---


async def user_can_access_document(db: AsyncSession, user_id: int | None, document_id: int) -> bool:
    """True, если документ существует и доступен пользователю."""
    return (
        await db.scalar(
            select(DocumentRecord.id).where(
                DocumentRecord.id == document_id, document_filter(user_id)
            )
        )
    ) is not None


async def user_can_manage_document(db: AsyncSession, user_id: int | None, document_id: int) -> bool:
    """True, если документ доступен — управлять им может тот, кто его видит."""
    return await user_can_access_document(db, user_id, document_id)


async def current_user_meeting_role(db: AsyncSession, user_id: int, meeting_id: int) -> str:
    """Роль пользователя относительно встречи (для UI/live-state).

    Автор → creator, остальные (с доступом) → object_manage (полный контроль в UI).
    """
    meeting = await db.get(MeetingSession, meeting_id)
    if meeting is None:
        return "unknown"
    if meeting.created_by_user_id == user_id or meeting.user_id == user_id:
        return "creator"
    return "object_manage"


async def accessible_payhub_project_ids(db: AsyncSession, user_id: int | None) -> list[int] | None:
    """PayHub project_id видимых объектов; None — ограничений нет (has_all).

    Пустой список — у пользователя нет видимых объектов с привязкой к PayHub.
    """
    if await user_has_all_objects(db, user_id):
        return None
    if user_id is None:
        return []
    rows = await db.execute(
        select(ProjectObject.payhub_project_id)
        .where(
            ProjectObject.payhub_project_id.is_not(None),
            ProjectObject.id.in_(accessible_object_ids_select(user_id)),
        )
        .distinct()
    )
    return sorted(int(pid) for pid in rows.scalars().all())
