"""Тесты RAG-папок (Этап 5), service-level (без HTTP).

build_meeting_rag_context открывает собственную сессию БД и не виден из тестовой
транзакции — поэтому prompt-блок проверяем через get_relevant_rag_chunks_for_meeting +
format_rag_chunks_block на тестовой сессии.
"""

from app.models.user import User
from app.models.meeting import MeetingSession
from app.models.document import DocumentRecord, DocumentChunk
from app.schemas.rag import RagFolderCreate
from app.services.rag_context import (
    create_rag_folder, attach_document_to_rag_folder, list_rag_folder_documents,
    attach_rag_folder_to_meeting, update_attached_rag_folder, get_rag_folder,
    get_relevant_rag_chunks_for_meeting, format_rag_chunks_block,
)


async def _mk_user(db, email: str) -> User:
    u = User(email=email, password_hash="x", role="user", is_active=True)
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_meeting(db, user_id: int) -> MeetingSession:
    m = MeetingSession(user_id=user_id, created_by_user_id=user_id, title="Встреча")
    db.add(m)
    await db.flush()
    await db.refresh(m)
    return m


async def _mk_ready_doc(db, name: str, text: str, user_id: int) -> DocumentRecord:
    doc = DocumentRecord(
        owner_user_id=user_id, original_name=name, file_ext=".pdf", status="ready",
        created_by_user_id=user_id,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    chunk = DocumentChunk(document_id=doc.id, chunk_index=0, text=text, page_number=1)
    db.add(chunk)
    await db.flush()
    return doc


async def test_create_folder_and_idempotent_attach_document(db):
    user = await _mk_user(db, "rag-doc@test.local")
    doc = await _mk_ready_doc(db, "Договор.pdf", "Условия поставки бетона марки М300", user.id)
    folder = await create_rag_folder(db, user.id, RagFolderCreate(title="Папка", path=["База", "Договоры"]))
    assert folder.id is not None
    assert folder.path == ["База", "Договоры"]

    a1 = await attach_document_to_rag_folder(db, folder.id, doc.id, user.id)
    a2 = await attach_document_to_rag_folder(db, folder.id, doc.id, user.id)
    assert a1.id == a2.id  # идемпотентно — та же связь
    docs = await list_rag_folder_documents(db, folder.id)
    assert len(docs) == 1
    assert docs[0].document_id == doc.id
    assert docs[0].chunks_count == 1


async def test_idempotent_attach_folder_to_meeting_and_toggle(db):
    user = await _mk_user(db, "rag-meet@test.local")
    meeting = await _mk_meeting(db, user.id)
    folder = await create_rag_folder(db, user.id, RagFolderCreate(title="Папка-встречи"))

    s1 = await attach_rag_folder_to_meeting(db, meeting.id, folder.id, user.id, included=True, priority=100)
    s2 = await attach_rag_folder_to_meeting(db, meeting.id, folder.id, user.id, included=True, priority=50)
    assert s1.source_id == s2.source_id  # тот же source, обновили priority
    assert s2.priority == 50
    assert s2.included is True

    from app.models.context_source import MeetingContextSource
    src = await db.get(MeetingContextSource, s2.source_id)
    off = await update_attached_rag_folder(db, src, included=False)
    assert off.included is False
    on = await update_attached_rag_folder(db, src, included=True)
    assert on.included is True


async def test_rag_chunks_included_builds_block(db):
    user = await _mk_user(db, "rag-block@test.local")
    meeting = await _mk_meeting(db, user.id)
    doc = await _mk_ready_doc(db, "Смета.pdf", "Стоимость арматуры и опалубки на объекте", user.id)
    folder = await create_rag_folder(db, user.id, RagFolderCreate(title="Сметы"))
    await attach_document_to_rag_folder(db, folder.id, doc.id, user.id)
    await attach_rag_folder_to_meeting(db, meeting.id, folder.id, user.id, included=True)

    chunks = await get_relevant_rag_chunks_for_meeting(db, meeting.id, "стоимость арматуры", limit=8)
    assert len(chunks) >= 1
    assert chunks[0]["folder_title"] == "Сметы"
    block = format_rag_chunks_block(chunks, max_chunks=8, max_chars=12000)
    assert "Релевантные фрагменты RAG-папок" in block
    assert "Сметы" in block


async def test_rag_chunks_excluded_when_not_included(db):
    user = await _mk_user(db, "rag-excl@test.local")
    meeting = await _mk_meeting(db, user.id)
    doc = await _mk_ready_doc(db, "Док.pdf", "Сроки выполнения работ по фундаменту", user.id)
    folder = await create_rag_folder(db, user.id, RagFolderCreate(title="Сроки"))
    await attach_document_to_rag_folder(db, folder.id, doc.id, user.id)
    await attach_rag_folder_to_meeting(db, meeting.id, folder.id, user.id, included=False)

    chunks = await get_relevant_rag_chunks_for_meeting(db, meeting.id, "сроки фундамент", limit=8)
    assert chunks == []


async def test_rag_chunks_excluded_when_folder_disabled(db):
    user = await _mk_user(db, "rag-disabled@test.local")
    meeting = await _mk_meeting(db, user.id)
    doc = await _mk_ready_doc(db, "Док.pdf", "Гарантийные обязательства подрядчика", user.id)
    folder = await create_rag_folder(db, user.id, RagFolderCreate(title="Гарантии"))
    await attach_document_to_rag_folder(db, folder.id, doc.id, user.id)
    await attach_rag_folder_to_meeting(db, meeting.id, folder.id, user.id, included=True)

    # отключаем папку напрямую — disabled не должна попадать в retrieval
    orm_folder = await get_rag_folder(db, folder.id)
    orm_folder.status = "disabled"
    await db.flush()

    chunks = await get_relevant_rag_chunks_for_meeting(db, meeting.id, "гарантийные обязательства", limit=8)
    assert chunks == []
