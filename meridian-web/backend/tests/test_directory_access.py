"""Минимальные тесты справочников и модели доступа (Этап 1 MVP).

Эндпоинты вызываются как обычные корутины (db/user передаются явно) — без HTTP.
"""

from app.models.user import User
from app.schemas.directory import (
    CustomerCreate,
    ProjectObjectCreate,
    DepartmentCreate,
    ObjectAccessGrantCreate,
)
from app.schemas.meeting import MeetingCreate
from app.api.customers import create_customer
from app.api.objects import create_object, create_object_access
from app.api.departments import create_department, add_department_user
from app.api.history import create_meeting
from app.services.access import user_can_access_object, user_can_access_meeting


async def _mk_user(db, email: str) -> User:
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def test_create_customer(db):
    owner = await _mk_user(db, "owner-cust@test.local")
    c = await create_customer(CustomerCreate(name="ООО «Заказчик»"), user=owner, db=db)
    assert c.id is not None
    assert c.owner_user_id == owner.id
    assert c.name == "ООО «Заказчик»"


async def test_create_object(db):
    owner = await _mk_user(db, "owner-obj@test.local")
    c = await create_customer(CustomerCreate(name="Заказчик-1"), user=owner, db=db)
    o = await create_object(
        ProjectObjectCreate(customer_name=c.name, name="Объект-1"), user=owner, db=db
    )
    assert o.id is not None
    assert o.customer_id == c.id
    assert o.customer_name == "Заказчик-1"


async def test_create_department(db):
    owner = await _mk_user(db, "owner-dept@test.local")
    d = await create_department(DepartmentCreate(name="Снабжение"), user=owner, db=db)
    assert d.id is not None
    assert d.name == "Снабжение"


async def test_assign_object_to_department(db):
    owner = await _mk_user(db, "owner-grant@test.local")
    c = await create_customer(CustomerCreate(name="З-Грант"), user=owner, db=db)
    o = await create_object(ProjectObjectCreate(customer_name=c.name, name="О-Грант"), user=owner, db=db)
    d = await create_department(DepartmentCreate(name="Д-Грант"), user=owner, db=db)
    g = await create_object_access(
        o.id,
        ObjectAccessGrantCreate(grantee_type="department", grantee_department_id=d.id, access_level="view"),
        user=owner,
        db=db,
    )
    assert g.id is not None
    assert g.grantee_type == "department"
    assert g.grantee_department_id == d.id


async def test_access_object_via_department(db):
    owner = await _mk_user(db, "owner-acc@test.local")
    member = await _mk_user(db, "member-acc@test.local")
    stranger = await _mk_user(db, "stranger-acc@test.local")

    c = await create_customer(CustomerCreate(name="З-Acc"), user=owner, db=db)
    o = await create_object(ProjectObjectCreate(customer_name=c.name, name="О-Acc"), user=owner, db=db)
    d = await create_department(DepartmentCreate(name="Д-Acc"), user=owner, db=db)
    await create_object_access(
        o.id, ObjectAccessGrantCreate(grantee_type="department", grantee_department_id=d.id), user=owner, db=db
    )
    await add_department_user(d.id, member.id, user=owner, db=db)
    await db.flush()

    assert await user_can_access_object(db, owner.id, o.id) is True      # владелец объекта
    assert await user_can_access_object(db, member.id, o.id) is True     # доступ через отдел
    assert await user_can_access_object(db, stranger.id, o.id) is False  # нет доступа


async def test_access_meeting_via_object(db):
    owner = await _mk_user(db, "owner-mtg@test.local")
    member = await _mk_user(db, "member-mtg@test.local")
    stranger = await _mk_user(db, "stranger-mtg@test.local")

    c = await create_customer(CustomerCreate(name="З-Mtg"), user=owner, db=db)
    o = await create_object(ProjectObjectCreate(customer_name=c.name, name="О-Mtg"), user=owner, db=db)
    d = await create_department(DepartmentCreate(name="Д-Mtg"), user=owner, db=db)
    await create_object_access(
        o.id, ObjectAccessGrantCreate(grantee_type="department", grantee_department_id=d.id), user=owner, db=db
    )
    await add_department_user(d.id, member.id, user=owner, db=db)

    m = await create_meeting(
        MeetingCreate(customer_id=c.id, object_id=o.id, meeting_topic="Тест"), user=owner, db=db
    )
    await db.flush()

    assert await user_can_access_meeting(db, owner.id, m.id) is True       # создатель/участник
    assert await user_can_access_meeting(db, member.id, m.id) is True      # через объект → отдел
    assert await user_can_access_meeting(db, stranger.id, m.id) is False   # нет доступа
