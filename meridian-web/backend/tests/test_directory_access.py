"""Тесты справочников и базового доступа к объектам/встречам.

Эндпоинты вызываются как обычные корутины (db/user передаются явно) — без HTTP.
Объект виден создателю (явный грант), владельцам грантов и has_all; чужому — нет.
Поля автора (owner_user_id/user_id) при удалении пользователя обнуляются (SET NULL), запись цела.
Матрица прав — tests/test_object_access.py.
"""


from app.models.user import User
from app.models.meeting import MeetingSession
from app.models.directory import Customer, ProjectObject
from app.models.document import DocumentRecord
from app.schemas.directory import CustomerCreate, ProjectObjectCreate, ProjectObjectUpdate
from app.schemas.meeting import MeetingCreate
from app.api.customers import create_customer
from app.api.objects import create_object, update_object
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
    # ASCII-имена: SQLite func.lower() не трогает кириллицу (на Postgres неважно).
    owner = await _mk_user(db, "owner-obj@test.local")
    c = await create_customer(CustomerCreate(name="Cust-1"), user=owner, db=db)
    o = await create_object(
        ProjectObjectCreate(customer_name=c.name, name="Obj-1"), user=owner, db=db
    )
    assert o.id is not None
    assert o.customer_id == c.id
    assert o.customer_name == "Cust-1"


async def test_object_visible_to_creator_only(db):
    owner = await _mk_user(db, "owner-acc@test.local")
    stranger = await _mk_user(db, "stranger-acc@test.local")
    c = await create_customer(CustomerCreate(name="Cust-Acc"), user=owner, db=db)
    o = await create_object(ProjectObjectCreate(customer_name=c.name, name="Obj-Acc"), user=owner, db=db)
    await db.flush()

    assert await user_can_access_object(db, owner.id, o.id) is True      # грант создателю
    assert await user_can_access_object(db, stranger.id, o.id) is False  # чужой без грантов


async def test_meeting_of_object_visible_by_object_access(db):
    owner = await _mk_user(db, "owner-mtg@test.local")
    stranger = await _mk_user(db, "stranger-mtg@test.local")
    c = await create_customer(CustomerCreate(name="Cust-Mtg"), user=owner, db=db)
    o = await create_object(ProjectObjectCreate(customer_name=c.name, name="Obj-Mtg"), user=owner, db=db)
    m = await create_meeting(
        MeetingCreate(object_id=o.id, meeting_topic="Тест"), user=owner, db=db
    )
    await db.flush()

    assert await user_can_access_meeting(db, owner.id, m.id) is True
    assert await user_can_access_meeting(db, stranger.id, m.id) is False  # доступ по объекту


async def test_meeting_and_document_survive_user_deletion(db):
    """Главный сценарий: удаление автора не уносит встречу/документ — поля → NULL."""
    owner = await _mk_user(db, "del-owner@test.local")
    c = await create_customer(CustomerCreate(name="Cust-Del"), user=owner, db=db)
    o = await create_object(ProjectObjectCreate(customer_name=c.name, name="Obj-Del"), user=owner, db=db)
    m = await create_meeting(
        MeetingCreate(object_id=o.id, meeting_topic="Тест-Del"), user=owner, db=db
    )
    doc = DocumentRecord(
        owner_user_id=owner.id, created_by_user_id=owner.id,
        original_name="смета.pdf", file_ext="pdf", status="ready",
    )
    db.add(doc)
    await db.flush()
    meeting_id, doc_id, cust_id, obj_id = m.id, doc.id, c.id, o.id

    await db.delete(owner)
    await db.flush()
    db.expire_all()

    m2 = await db.get(MeetingSession, meeting_id)
    doc2 = await db.get(DocumentRecord, doc_id)
    c2 = await db.get(Customer, cust_id)
    o2 = await db.get(ProjectObject, obj_id)

    assert m2 is not None and m2.user_id is None and m2.created_by_user_id is None
    assert doc2 is not None and doc2.owner_user_id is None and doc2.created_by_user_id is None
    assert c2 is not None and c2.owner_user_id is None
    assert o2 is not None and o2.owner_user_id is None


async def test_object_tender_won_default_set_and_null_ignored(db):
    owner = await _mk_user(db, "owner-won@test.local")
    o = await create_object(
        ProjectObjectCreate(customer_name="Cust-Won", name="Obj-Won"), user=owner, db=db
    )
    assert o.tender_won is False

    o = await update_object(o.id, ProjectObjectUpdate(tender_won=True), user=owner, db=db)
    assert o.tender_won is True

    # явный null не должен ронять NOT NULL и не меняет значение
    o = await update_object(
        o.id, ProjectObjectUpdate.model_validate({"tender_won": None, "notes": "x"}),
        user=owner, db=db,
    )
    assert o.tender_won is True
    assert o.notes == "x"

    o = await update_object(o.id, ProjectObjectUpdate(tender_won=False), user=owner, db=db)
    assert o.tender_won is False

    created = await create_object(
        ProjectObjectCreate(customer_name="Cust-Won", name="Another-Tender", tender_won=True),
        user=owner, db=db,
    )
    assert created.tender_won is True
