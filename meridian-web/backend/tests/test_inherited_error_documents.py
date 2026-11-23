"""Унаследованные не готовые документы: видны в списке источников, но не попадают в контекст LLM."""

from app.services.document_context import effective_meeting_document_ids
from app.services.meeting_documents import list_meeting_document_items

from .test_offer_submissions import _doc, _meeting, _setup


async def test_error_object_document_listed_but_not_in_context(db):
    user, _, obj, _ = await _setup(db)
    ready = await _doc(db, user, "ready.txt", obj)
    broken = await _doc(db, user, "broken.pdf", obj, status="error")
    busy = await _doc(db, user, "busy.pdf", obj, status="processing")
    meeting = await _meeting(db, user, obj)

    assert await effective_meeting_document_ids(db, meeting) == {ready.id}
    items = {i.document_id: i for i in await list_meeting_document_items(db, meeting, include_not_ready=True)}
    assert set(items) == {ready.id, broken.id, busy.id}
    assert items[ready.id].included is True
    assert items[broken.id].status == "error" and items[broken.id].included is False
    assert items[broken.id].source == "object"
    assert items[busy.id].included is False
    # без флага (десктоп/мобильное приложение) список прежний — только готовые
    default = {i.document_id for i in await list_meeting_document_items(db, meeting)}
    assert default == {ready.id}


async def test_display_name_in_meeting_item(db):
    user, _, obj, _ = await _setup(db)
    doc = await _doc(db, user, "КП 343 · 2026-11-09 · 001 Отправка · Смета.docx", obj)
    meeting = await _meeting(db, user, obj)
    items = await list_meeting_document_items(db, meeting, include_not_ready=True)
    assert items[0].display_name == "Смета.docx"
    assert items[0].model_dump()["display_name"] == "Смета.docx"
    assert doc.id == items[0].document_id
