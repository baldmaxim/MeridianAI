"""Регрессы для четырёх багов AI-выходного слоя (fix(ai)).

A — не-ASCII заголовок X-Title ломал все вызовы OpenRouter;
B — len(doc.content) при content=None (S3-документы) ронял request_suggestion;
C — Deepgram/legacy финальные сегменты не попадали в committed-store → finalize видел пустой транскрипт;
D — make_default нарушал partial-unique uq_ai_profile_default из-за порядка flush.
"""

from datetime import datetime

import pytest
from sqlalchemy import select, func

from app.core.llm.client import OPENROUTER_APP_HEADERS, LLMClient
from app.core.context.document_loader import DocumentLoader, MeetingDocument
from app.core.transcription.models import TranscriptSegment, SegmentOrigin
from app.services.session_manager import SessionManager
from app.services import ai_settings as ais
from app.models.user import User
from app.models.meeting import MeetingSession, TranscriptSegmentRecord
from app.models.ai_settings import AISettingsProfile


# ========================= Bug A =========================

def test_openrouter_headers_are_ascii():
    """Все значения HTTP-заголовков OpenRouter кодируются в ASCII без ошибок."""
    for key, value in OPENROUTER_APP_HEADERS.items():
        key.encode("ascii")    # не должно бросать
        value.encode("ascii")  # не должно бросать (Bug A: тут падал em-dash)
    assert "—" not in OPENROUTER_APP_HEADERS["X-Title"]  # нет em-dash


def test_llmclient_constructs_with_ascii_headers():
    """LLMClient строится без ошибок, дефолтные заголовки ASCII-safe."""
    client = LLMClient(api_key="test-key-not-used")
    assert client.model
    # повторно гарантируем ASCII-кодируемость заголовков, используемых клиентом
    for value in OPENROUTER_APP_HEADERS.values():
        value.encode("ascii")


# ========================= Bug B =========================

def _doc(filename, content, doc_type="other", pages=1):
    return MeetingDocument(filename=filename, content=content, doc_type=doc_type,
                           loaded_at=datetime(2026, 1, 1, 10, 0), page_count=pages)


def test_document_loader_none_content_does_not_crash():
    """S3-документ с content=None не ломает сборку контекста (Bug B)."""
    dl = DocumentLoader()
    dl.documents.append(_doc("s3-vor.pdf", None, "bor", pages=3))
    # обе ветки сборки промпта не должны падать на len(None)
    ctx = dl.get_context_for_prompt()
    doc_ctx = dl.get_document_context()
    assert isinstance(ctx, str) and isinstance(doc_ctx, str)


def test_document_loader_skips_empty_keeps_legacy():
    """Документ с None-content пропускается, legacy inline-текст остаётся в контексте."""
    dl = DocumentLoader()
    dl.documents.append(_doc("s3.pdf", None, "bor"))            # S3 → пропускаем
    dl.documents.append(_doc("legacy.txt", "Цена бетона 1200 тенге", "estimate"))
    out = dl.get_document_context()
    assert "Цена бетона 1200 тенге" in out
    assert "legacy.txt" in out and "s3.pdf" not in out


def test_document_loader_all_empty_returns_clean():
    """Когда все документы пустые — без мусорного заголовка 'ДОКУМЕНТЫ ВСТРЕЧИ'."""
    dl = DocumentLoader()
    dl.documents.append(_doc("a.pdf", None))
    dl.documents.append(_doc("b.pdf", "   "))
    assert dl.get_document_context() == ""
    assert "ДОКУМЕНТЫ ВСТРЕЧИ" not in dl.get_context_for_prompt()


# ========================= Bug C =========================

def _seg(text, partial_speaker="Спикер 1"):
    return TranscriptSegment(speaker=partial_speaker, text=text, start_time=0.0,
                             end_time=2.0, timestamp=datetime(2026, 1, 1, 10, 0), confidence=0.9)


def test_legacy_final_segment_enters_committed_store():
    """Финальный Deepgram/legacy-сегмент попадает в committed_segments (Bug C)."""
    sm = SessionManager(1)
    sm._ws_send = None  # без WS — проверяем, что персист не зависит от рассылки
    sm._on_legacy_transcript(_seg("Цена слишком высокая"), is_partial=False)
    assert len(sm.committed_segments) == 1
    cs = sm.committed_segments[0]
    assert cs.text == "Цена слишком высокая"
    assert cs.origin == SegmentOrigin.LIVE_COMMITTED
    assert cs.speaker_label == "Спикер 1"


def test_legacy_partial_segment_not_persisted():
    """Партиалы не попадают в committed-store (нет дублей)."""
    sm = SessionManager(1)
    sm._ws_send = None
    sm._on_legacy_transcript(_seg("частичный текст"), is_partial=True)
    assert len(sm.committed_segments) == 0


def test_legacy_empty_text_not_persisted():
    """Пустой финал не создаёт committed-сегмент."""
    sm = SessionManager(1)
    sm._ws_send = None
    sm._on_legacy_transcript(_seg("   "), is_partial=False)
    assert len(sm.committed_segments) == 0


async def test_persisted_segments_make_finalize_nonempty(db):
    """Сохранённый transcript segment → finalize видит непустой транскрипт (Bug C, конец цепочки)."""
    from app.services.meeting_finalize import _gather_inputs
    owner = User(email="bugc@test.local", password_hash="x", role="user", is_active=True)
    db.add(owner); await db.flush(); await db.refresh(owner)
    m = MeetingSession(user_id=owner.id, created_by_user_id=owner.id, is_active=False,
                       status="finalized", started_at=datetime(2026, 1, 1, 10, 0))
    db.add(m); await db.flush(); await db.refresh(m)
    db.add(TranscriptSegmentRecord(
        session_id=m.id, segment_id="segc0000001", text="Цена бетона обсуждается",
        start_time=0.0, end_time=2.0, wall_clock=datetime(2026, 1, 1, 10, 0),
        speaker_id="spk1", speaker_label="Спикер 1", origin="live_committed", word_count=3,
    ))
    await db.flush()
    _block, transcript_text, _docs, _names = await _gather_inputs(db, m)
    assert transcript_text.strip()                  # НЕ пусто → finalize не уйдёт в partial(empty)
    assert "Цена бетона" in transcript_text


# ========================= Bug D =========================

class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _FakeSession:
    """Фейковая сессия: фиксирует состояние is_default на каждом flush."""

    def __init__(self, others):
        self._others = others
        self.target = None
        self.snapshots = []  # [(target.is_default, [o.is_default ...]) на момент flush]

    async def execute(self, stmt):
        return _FakeResult(self._others)

    async def flush(self):
        self.snapshots.append((self.target.is_default, [o.is_default for o in self._others]))


async def test_make_default_unsets_before_setting():
    """make_default снимает старый default ДО установки нового (Bug D: порядок flush)."""
    target = AISettingsProfile(owner_user_id=1, name="target", is_default=False)
    old = AISettingsProfile(owner_user_id=1, name="old", is_default=True)
    fake = _FakeSession([old])
    fake.target = target

    await ais.make_default(fake, target)

    # первый flush — старый default уже снят, новый ещё не выставлен
    assert fake.snapshots[0] == (False, [False])
    # итог — ровно один default
    assert target.is_default is True
    assert old.is_default is False


async def test_make_default_db_single_default(db):
    """Интеграция: переключение default на профиль с меньшим id не падает, один default."""
    owner = User(email="bugd@test.local", password_hash="x", role="user", is_active=True)
    db.add(owner); await db.flush(); await db.refresh(owner)
    p1 = await ais.get_or_create_default_profile(db, owner.id)  # меньший id, default
    p2 = AISettingsProfile(owner_user_id=owner.id, name="second", suggestion_mode="fast",
                           created_by_user_id=owner.id)
    ais.apply_mode_defaults(p2)
    db.add(p2); await db.flush(); await db.refresh(p2)

    await ais.make_default(db, p2)            # default → больший id
    await ais.make_default(db, p1)            # default → меньший id (раньше падало)

    defaults = (await db.execute(select(func.count(AISettingsProfile.id)).where(
        AISettingsProfile.owner_user_id == owner.id,
        AISettingsProfile.is_default == True,  # noqa: E712
    ))).scalar()
    assert defaults == 1
    await db.refresh(p1)
    assert p1.is_default is True
