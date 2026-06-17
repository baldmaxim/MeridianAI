"""Тесты статической сборки Context Pack и preview-эндпоинта (Этап 6)."""

import pytest
from fastapi import HTTPException

from app.models.user import User
from app.models.meeting import MeetingSession
from app.models.document import DocumentRecord, DocumentChunk
from app.schemas.rag import RagFolderCreate
from app.services.rag_context import (
    create_rag_folder, attach_document_to_rag_folder, attach_rag_folder_to_meeting,
)
from app.services.context_pack import assemble_static_context_pack_for_meeting
from app.api.context_preview import context_preview


async def _mk_user(db, email: str) -> User:
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_meeting(db, user_id: int, topic=None, notes=None) -> MeetingSession:
    m = MeetingSession(
        user_id=user_id, created_by_user_id=user_id, title="Встреча",
        meeting_topic=topic, meeting_notes=notes,
    )
    db.add(m)
    await db.flush()
    await db.refresh(m)
    return m


async def _mk_ready_doc(db, name, text, user_id) -> DocumentRecord:
    doc = DocumentRecord(owner_user_id=user_id, original_name=name, file_ext=".pdf",
                         status="ready", created_by_user_id=user_id)
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text=text, page_number=1))
    await db.flush()
    return doc


def _block(pack, kind):
    return next((b for b in pack.blocks if b.kind == kind), None)


async def test_preview_has_meeting_context_block(db):
    user = await _mk_user(db, "prev-mc@test.local")
    meeting = await _mk_meeting(db, user.id, topic="Контракт ЖК Рассвет", notes="Целевая сумма 10 млн")
    pack = await assemble_static_context_pack_for_meeting(
        db, meeting_id=meeting.id, viewer_user_id=user.id, mode="manual",
    )
    mc = _block(pack, "meeting_context")
    assert mc is not None and mc.enabled is True
    assert "Контракт ЖК Рассвет" in mc.content
    # live-реплик в preview нет — блок диалога честно выключен
    rd = _block(pack, "recent_dialog")
    assert rd is not None and rd.enabled is False and rd.reason


async def test_preview_rag_block_present_when_included(db):
    user = await _mk_user(db, "prev-rag@test.local")
    meeting = await _mk_meeting(db, user.id, topic="Смета")
    doc = await _mk_ready_doc(db, "Смета.pdf", "Стоимость арматуры и опалубки", user.id)
    folder = await create_rag_folder(db, user.id, RagFolderCreate(title="Сметы"))
    await attach_document_to_rag_folder(db, folder.id, doc.id, user.id)
    await attach_rag_folder_to_meeting(db, meeting.id, folder.id, user.id, included=True)

    pack = await assemble_static_context_pack_for_meeting(
        db, meeting_id=meeting.id, viewer_user_id=user.id, mode="manual", query_text="стоимость арматуры",
    )
    rag = _block(pack, "rag")
    assert rag is not None and rag.enabled is True
    assert rag.source_count >= 1
    assert "Сметы" in rag.content


async def test_preview_rag_absent_when_not_included(db):
    user = await _mk_user(db, "prev-rag-off@test.local")
    meeting = await _mk_meeting(db, user.id, topic="Смета")
    doc = await _mk_ready_doc(db, "Смета.pdf", "Стоимость арматуры", user.id)
    folder = await create_rag_folder(db, user.id, RagFolderCreate(title="Сметы"))
    await attach_document_to_rag_folder(db, folder.id, doc.id, user.id)
    await attach_rag_folder_to_meeting(db, meeting.id, folder.id, user.id, included=False)

    pack = await assemble_static_context_pack_for_meeting(
        db, meeting_id=meeting.id, viewer_user_id=user.id, mode="manual", query_text="стоимость арматуры",
    )
    rag = _block(pack, "rag")
    assert rag is not None
    assert rag.enabled is False
    assert rag.content == ""


async def test_api_preview_returns_blocks(db):
    user = await _mk_user(db, "prev-api@test.local")
    meeting = await _mk_meeting(db, user.id, topic="Тема", notes="Заметки")
    out = await context_preview(
        meeting_id=meeting.id, mode="manual", q=None, preview_chars_per_block=1200,
        user=user, db=db,
    )
    assert out["meeting_id"] == meeting.id
    assert out["mode"] == "manual"
    kinds = {b["kind"] for b in out["blocks"]}
    assert "meeting_context" in kinds
    assert any(b["kind"] == "meeting_context" and b["enabled"] for b in out["blocks"])


async def test_api_preview_404_for_missing_meeting(db):
    user = await _mk_user(db, "prev-404@test.local")
    with pytest.raises(HTTPException) as exc:
        await context_preview(
            meeting_id=999999, mode="manual", q=None, preview_chars_per_block=1200,
            user=user, db=db,
        )
    assert exc.value.status_code == 404
