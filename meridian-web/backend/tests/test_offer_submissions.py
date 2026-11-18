"""Подачи КП: фильтр наследования документов объекта, PATCH/POST встречи, список подач, DocumentResponse."""

import pytest
from fastapi import HTTPException

from app.api.documents import create_s3_document_upload
from app.api.history import create_meeting, get_meeting_detail, list_meetings, update_meeting
from app.api.objects import list_offer_submissions
from app.models.directory import Customer, ProjectObject
from app.models.document import DocumentRecord
from app.models.meeting import MeetingSession
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentUploadSessionRequest, MeetingDocumentItem
from app.schemas.meeting import MeetingCreate, MeetingUpdate
from app.models.document import DocumentChunk
from app.services import document_context
from app.services.document_context import build_meeting_doc_context, effective_meeting_document_ids
from app.services.meeting_documents import attach_document, list_meeting_document_items
from app.services.offer_submissions import offer_submission_from_meta, public_doc_meta

from .test_stage4_documents import _enable_s3, commit_db  # noqa: F401

SUB_1 = "001 15.06.2026 Первичная"
SUB_2 = "002 29.06.2026 Скидка"


async def _setup(db):
    user = User(email="own@t.local", password_hash="x", role="user", is_active=True)
    cust = Customer(name="A")
    db.add_all([user, cust])
    await db.flush()
    obj = ProjectObject(customer_id=cust.id, name="Объект 1")
    obj2 = ProjectObject(customer_id=cust.id, name="Объект 2")
    db.add_all([obj, obj2])
    await db.flush()
    return user, cust, obj, obj2


async def _doc(db, user, name, obj, *, submission=None, date=None, status="ready", meta=None):
    if meta is None and date is not None:
        meta = {"import_source": {"kind": "offer", "submission": submission, "date": date}}
    d = DocumentRecord(owner_user_id=user.id, created_by_user_id=user.id, original_name=name,
                       file_ext=".txt", status=status, s3_key=f"k/{name}", object_id=obj.id,
                       customer_id=obj.customer_id, offer_submission=submission, doc_meta=meta)
    db.add(d)
    await db.flush()
    return d


async def _meeting(db, user, obj, offer_submission=None):
    m = MeetingSession(user_id=user.id, created_by_user_id=user.id, is_active=True, status="active",
                       customer_id=obj.customer_id, object_id=obj.id, offer_submission=offer_submission)
    db.add(m)
    await db.flush()
    return m


# --- (а) фильтр наследования ---


async def test_null_submission_inherits_all_object_documents(db):
    user, _, obj, _ = await _setup(db)
    common = await _doc(db, user, "ocr.txt", obj)
    a = await _doc(db, user, "a.txt", obj, submission=SUB_1)
    b = await _doc(db, user, "b.txt", obj, submission=SUB_2)
    meeting = await _meeting(db, user, obj)
    assert await effective_meeting_document_ids(db, meeting) == {common.id, a.id, b.id}


async def test_selected_submission_takes_common_plus_own_only(db):
    user, _, obj, _ = await _setup(db)
    common = await _doc(db, user, "ocr.txt", obj)
    a = await _doc(db, user, "a.txt", obj, submission=SUB_1)
    b = await _doc(db, user, "b.txt", obj, submission=SUB_2)
    bucket = await _doc(db, user, "free.txt", obj, submission="")
    meeting = await _meeting(db, user, obj, SUB_2)
    assert await effective_meeting_document_ids(db, meeting) == {common.id, b.id}
    items = {i.document_id: i for i in await list_meeting_document_items(db, meeting)}
    assert set(items) == {common.id, b.id}
    assert items[b.id].offer_submission == SUB_2 and items[common.id].offer_submission is None
    assert a.id not in items and bucket.id not in items


async def test_empty_string_bucket_is_a_submission(db):
    user, _, obj, _ = await _setup(db)
    common = await _doc(db, user, "ocr.txt", obj)
    a = await _doc(db, user, "a.txt", obj, submission=SUB_1)
    bucket = await _doc(db, user, "free.txt", obj, submission="")
    meeting = await _meeting(db, user, obj, "")
    assert await effective_meeting_document_ids(db, meeting) == {common.id, bucket.id}
    assert a.id not in await effective_meeting_document_ids(db, meeting)


async def test_explicitly_attached_doc_of_other_submission_is_included(db):
    user, _, obj, _ = await _setup(db)
    a = await _doc(db, user, "a.txt", obj, submission=SUB_1)
    b = await _doc(db, user, "b.txt", obj, submission=SUB_2)
    meeting = await _meeting(db, user, obj, SUB_2)
    await attach_document(db, meeting, a, user.id)
    assert await effective_meeting_document_ids(db, meeting) == {a.id, b.id}


async def test_customer_documents_without_object_ignore_submission(db):
    user, cust, obj, _ = await _setup(db)
    cd = DocumentRecord(owner_user_id=user.id, created_by_user_id=user.id, original_name="c.txt",
                        file_ext=".txt", status="ready", customer_id=cust.id)
    db.add(cd)
    await db.flush()
    meeting = await _meeting(db, user, obj, SUB_1)
    assert await effective_meeting_document_ids(db, meeting) == {cd.id}


# --- (б) POST / PATCH встречи ---


async def test_create_meeting_validates_submission(db):
    user, _, obj, obj2 = await _setup(db)
    await _doc(db, user, "a.txt", obj, submission=SUB_1)
    m = await create_meeting(MeetingCreate(object_id=obj.id, offer_submission=SUB_1), user=user, db=db)
    assert m.offer_submission == SUB_1
    with pytest.raises(HTTPException) as e:
        await create_meeting(MeetingCreate(object_id=obj2.id, offer_submission=SUB_1), user=user, db=db)
    assert e.value.status_code == 422 and e.value.detail == "Подача не найдена у объекта"
    with pytest.raises(HTTPException) as e:
        await create_meeting(MeetingCreate(offer_submission=SUB_1), user=user, db=db)
    assert e.value.status_code == 422
    plain = await create_meeting(MeetingCreate(object_id=obj.id), user=user, db=db)
    assert plain.offer_submission is None


async def test_patch_validates_resets_and_clears(db):
    user, _, obj, obj2 = await _setup(db)
    await _doc(db, user, "a.txt", obj, submission=SUB_1)
    await _doc(db, user, "b.txt", obj2, submission=SUB_2)
    await _doc(db, user, "free.txt", obj, submission="")
    meeting = await _meeting(db, user, obj)

    with pytest.raises(HTTPException) as e:  # чужая подача (она у другого объекта)
        await update_meeting(meeting.id, MeetingUpdate(offer_submission=SUB_2), user=user, db=db)
    assert e.value.status_code == 422 and meeting.offer_submission is None

    r = await update_meeting(meeting.id, MeetingUpdate(offer_submission=SUB_1), user=user, db=db)
    assert r.offer_submission == SUB_1
    # прочие поля подачу не трогают; тот же object_id — не сброс
    r = await update_meeting(meeting.id, MeetingUpdate(meeting_topic="т", object_id=obj.id), user=user, db=db)
    assert r.offer_submission == SUB_1
    # "" — корзина — допустима
    r = await update_meeting(meeting.id, MeetingUpdate(offer_submission=""), user=user, db=db)
    assert r.offer_submission == ""
    # явный null — сброс
    r = await update_meeting(meeting.id, MeetingUpdate(offer_submission=None), user=user, db=db)
    assert r.offer_submission is None

    await update_meeting(meeting.id, MeetingUpdate(offer_submission=SUB_1), user=user, db=db)
    # смена объекта без offer_submission — сброс
    r = await update_meeting(meeting.id, MeetingUpdate(object_id=obj2.id), user=user, db=db)
    assert r.object_id == obj2.id and r.offer_submission is None
    # смена объекта вместе с подачей нового объекта
    r = await update_meeting(
        meeting.id, MeetingUpdate(object_id=obj.id, offer_submission=SUB_1), user=user, db=db)
    assert r.object_id == obj.id and r.offer_submission == SUB_1
    # подача проверяется против нового объекта
    with pytest.raises(HTTPException) as e:
        await update_meeting(
            meeting.id, MeetingUpdate(object_id=obj2.id, offer_submission=SUB_1), user=user, db=db)
    assert e.value.status_code == 422


async def test_meeting_responses_carry_offer_submission(db):
    user, _, obj, _ = await _setup(db)
    await _doc(db, user, "a.txt", obj, submission=SUB_1)
    meeting = await _meeting(db, user, obj, SUB_1)
    meeting.is_active = False
    await db.flush()
    detail = await get_meeting_detail(meeting.id, user=user, db=db)
    assert detail.offer_submission == SUB_1
    listed = await list_meetings(
        customer_id=None, object_id=obj.id, status=None, q=None, include_active=True, user=user, db=db)
    assert [m.offer_submission for m in listed] == [SUB_1]


# --- (в) GET /objects/{id}/offer-submissions ---


async def test_offer_submissions_groups_label_and_sorting(db):
    user, _, obj, obj2 = await _setup(db)
    await _doc(db, user, "ocr.txt", obj, meta={"import_source": {"kind": "ocr"}})
    await _doc(db, user, "a1.txt", obj, submission=SUB_1, date="2026-06-20")
    await _doc(db, user, "a2.txt", obj, submission=SUB_1, date="2026-06-15")
    await _doc(db, user, "a3.txt", obj, submission=SUB_1, status="pending", date="2026-06-18")
    await _doc(db, user, "b.txt", obj, submission=SUB_2, date="2026-06-29")
    await _doc(db, user, "free.txt", obj, submission="")
    await _doc(db, user, "x.txt", obj, submission="000 Без даты")
    await _doc(db, user, "other.txt", obj2, submission="999 Чужая", date="2026-12-01")

    res = await list_offer_submissions(obj.id, user=user, db=db)
    assert [(g.key, g.label, g.date, g.document_count) for g in res] == [
        (SUB_2, SUB_2, "2026-06-29", 1),
        (SUB_1, SUB_1, "2026-06-15", 3),
        ("000 Без даты", "000 Без даты", None, 1),
        ("", "Вне папок подач", None, 1),
    ]


async def test_offer_submissions_unknown_object_is_404(db):
    user, _, _, _ = await _setup(db)
    with pytest.raises(HTTPException) as e:
        await list_offer_submissions(99999, user=user, db=db)
    assert e.value.status_code == 404
    assert await list_offer_submissions((await _setup_obj(db, user)).id, user=user, db=db) == []


async def _setup_obj(db, user):
    cust = Customer(name="Z")
    db.add(cust)
    await db.flush()
    obj = ProjectObject(customer_id=cust.id, name="Пустой")
    db.add(obj)
    await db.flush()
    return obj


# --- (г) DocumentResponse без локального пути ---


async def test_document_response_hides_import_path_without_mutating_orm(db):
    user, _, obj, _ = await _setup(db)
    meta = {"import_source": {"kind": "offer", "submission": SUB_1, "date": "2026-06-15",
                              "path": "C:\\Users\\op\\КП\\a.xlsx", "sha256": "abc"}}
    doc = await _doc(db, user, "a.xlsx", obj, submission=SUB_1, meta=meta)
    resp = DocumentResponse.model_validate(doc)
    assert resp.offer_submission == SUB_1
    assert "path" not in resp.doc_meta["import_source"]
    assert resp.doc_meta["import_source"]["sha256"] == "abc"
    assert doc.doc_meta["import_source"]["path"] == "C:\\Users\\op\\КП\\a.xlsx"  # ORM не тронут
    item = (await list_meeting_document_items(db, await _meeting(db, user, obj)))[0]
    assert isinstance(item, MeetingDocumentItem) and "path" not in item.doc_meta["import_source"]


def test_public_doc_meta_passthrough():
    assert public_doc_meta(None) is None
    assert public_doc_meta({"a": 1}) == {"a": 1}
    assert public_doc_meta({"import_source": "x"}) == {"import_source": "x"}


# --- (д) offer_submission_from_meta ---


@pytest.mark.parametrize("source,expected", [
    (None, None),
    ("строка", None),
    ({}, None),
    ({"kind": "ocr", "submission": "x"}, None),
    ({"kind": "tenderhub_calculation"}, None),
    ({"kind": "offer", "submission": SUB_1}, SUB_1),
    ({"kind": "offer", "submission": ""}, ""),
    ({"kind": "offer"}, ""),
    ({"kind": "offer", "submission": None}, ""),
    ({"kind": "offer", "submission": 5}, ""),
    ({"kind": "offer", "submission": "x" * 400}, "x" * 300),
])
def test_offer_submission_from_meta(source, expected):
    assert offer_submission_from_meta(source) == expected


# --- заполнение при создании документа ---


@pytest.mark.parametrize("source,expected", [
    ({"kind": "offer", "submission": SUB_2}, SUB_2),
    ({"kind": "offer", "submission": ""}, ""),
    ({"kind": "ocr", "submission": SUB_2}, None),
    (None, None),
])
async def test_upload_session_fills_offer_submission(commit_db, monkeypatch, source, expected):  # noqa: F811
    _enable_s3(monkeypatch)
    user = User(email="imp@t.local", password_hash="x", role="user", is_active=True)
    commit_db.add(user)
    await commit_db.flush()
    resp = await create_s3_document_upload(
        commit_db, user, DocumentUploadSessionRequest(filename="o.docx", size_bytes=10),
        meeting_id=None, import_source=source,
    )
    assert (await commit_db.get(DocumentRecord, resp.document_id)).offer_submission == expected


# --- строка «Обсуждаемая подача КП» в блоке документов ---


class _SessionCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


@pytest.mark.parametrize("submission,header", [
    (SUB_1, f"Обсуждаемая подача КП: {SUB_1}"),
    ("", "Обсуждаемая подача КП: Вне папок подач"),
    (None, None),
])
async def test_doc_context_block_names_submission(db, monkeypatch, submission, header):
    monkeypatch.setattr(document_context, "async_session", lambda: _SessionCtx(db))
    user, _, obj, _ = await _setup(db)
    doc = await _doc(db, user, "a.txt", obj, submission=submission)
    db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text="неустойка за просрочку платежа"))
    meeting = await _meeting(db, user, obj, submission)
    block = await build_meeting_doc_context(meeting.id, "неустойка")
    assert "Релевантные фрагменты документов:" in block
    assert (block.startswith(header + "\n\n") if header else block.startswith("Релевантные")), block[:80]
