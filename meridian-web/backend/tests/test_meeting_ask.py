# -*- coding: utf-8 -*-
"""«Спросить» по встрече: контекст в промпте, доступ, валидация, ошибки LLM; заметки в промпте протокола."""

from datetime import datetime

import pytest

from app.core.llm.finalization_prompt import build_user_prompt
from app.models.document import DocumentChunk, DocumentRecord
from app.models.meeting import MeetingDocumentRecord, MeetingSession
from app.services import meeting_ask
from app.services.meeting_finalize import _gather_inputs

from .test_desktop_api import (  # noqa: F401 — фикстуры и помощники десктоп-тестов
    _bearer, _device, _jwt, _meeting, _seg, _user, client, sm,
)

SECRET_NOTE = "проверить неустойку по пункту 12"


class _FakeLLM:
    prompts: list[str] = []
    reply: str | None = "Неустойка 0,1% в день [документ: Договор, стр. 3]."

    def __init__(self, **kw):
        self.kw = kw

    def set_system_prompt(self, prompt):
        self.system = prompt

    async def get_suggestion_async(self, prompt, max_tokens=None):
        _FakeLLM.prompts.append(prompt)
        return _FakeLLM.reply


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    _FakeLLM.prompts = []
    _FakeLLM.reply = "Неустойка 0,1% в день [документ: Договор, стр. 3]."

    async def _keys():
        return {"openrouter": "test-key"}

    monkeypatch.setattr(meeting_ask, "LLMClient", _FakeLLM)
    monkeypatch.setattr(meeting_ask, "load_api_keys", _keys)


async def _prepare(sm, client, token) -> int:
    """Встреча с транскриптом, заметкой и документом."""
    mid = (await _meeting(client, token))["meeting_id"]
    h = _bearer(token)
    r = await client.put(f"/api/desktop/meetings/{mid}/segments", headers=h, json={"segments": [
        _seg("s1", "Срок сдачи фасада сдвигаем на март", start=65.0, end=70.0),
        _seg("s2", "Согласны, но без штрафов", start=72.0, end=75.0, channel="system"),
    ]})
    assert r.status_code == 200, r.text
    r = await client.patch(f"/api/desktop/meetings/{mid}", headers=h, json={
        "notes": [{"at_seconds": 66, "text": SECRET_NOTE}]})
    assert r.status_code == 200, r.text
    async with sm() as db:
        doc = DocumentRecord(original_name="Договор.pdf", file_ext=".pdf", status="ready")
        db.add(doc)
        await db.flush()
        db.add(DocumentChunk(document_id=doc.id, chunk_index=0, page_number=3,
                             text="Неустойка за просрочку составляет 0,1% за каждый день"))
        db.add(MeetingDocumentRecord(session_id=mid, document_id=doc.id, included=True, priority=100))
        await db.commit()
    return mid


# ---------- десктоп ----------

async def test_desktop_ask_returns_answer_and_context_in_prompt(sm, client):
    token = await _device(sm, await _user(sm))
    mid = await _prepare(sm, client, token)

    r = await client.post(f"/api/desktop/meetings/{mid}/ask", headers=_bearer(token),
                          json={"question": "какая неустойка в договоре?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"].startswith("Неустойка 0,1%")
    kinds = {s["kind"] for s in body["sources"]}
    assert {"transcript", "note", "document"} <= kinds
    doc = next(s for s in body["sources"] if s["kind"] == "document")
    assert doc == {"kind": "document", "title": "Договор.pdf", "ref": "стр. 3"}
    tr = next(s for s in body["sources"] if s["kind"] == "transcript")
    assert tr["ref"] == "01:05–01:12"

    prompt = _FakeLLM.prompts[-1]
    assert "Срок сдачи фасада сдвигаем на март" in prompt      # транскрипт
    assert "Мы:" in prompt and "Оппонент:" in prompt           # стороны
    assert f"[01:06] {SECRET_NOTE}" in prompt                  # заметки
    assert "Неустойка за просрочку составляет 0,1%" in prompt  # документ
    assert "какая неустойка в договоре?" in prompt             # вопрос


async def test_desktop_ask_works_after_finalization(sm, client):
    token = await _device(sm, await _user(sm))
    mid = await _prepare(sm, client, token)
    r = await client.post(f"/api/desktop/meetings/{mid}/finalize", headers=_bearer(token))
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/desktop/meetings/{mid}/ask", headers=_bearer(token),
                          json={"question": "что решили?"})
    assert r.status_code == 200, r.text


async def test_desktop_ask_foreign_meeting_404_and_no_token_401(sm, client):
    owner_token = await _device(sm, await _user(sm))
    mid = (await _meeting(client, owner_token))["meeting_id"]
    other_token = await _device(sm, await _user(sm, email="other@test.local"))

    r = await client.post(f"/api/desktop/meetings/{mid}/ask", headers=_bearer(other_token),
                          json={"question": "q"})
    assert r.status_code == 404
    r = await client.post(f"/api/desktop/meetings/{mid}/ask", json={"question": "q"})
    assert r.status_code == 401
    assert _FakeLLM.prompts == []


@pytest.mark.parametrize("question", ["", "   ", "я" * 1001])
async def test_desktop_ask_invalid_question_422(sm, client, question):
    token = await _device(sm, await _user(sm))
    mid = (await _meeting(client, token))["meeting_id"]
    r = await client.post(f"/api/desktop/meetings/{mid}/ask", headers=_bearer(token),
                          json={"question": question})
    assert r.status_code == 422
    assert _FakeLLM.prompts == []


async def test_desktop_ask_llm_failure_502_without_leaks(sm, client):
    token = await _device(sm, await _user(sm))
    mid = (await _meeting(client, token))["meeting_id"]
    _FakeLLM.reply = None
    r = await client.post(f"/api/desktop/meetings/{mid}/ask", headers=_bearer(token),
                          json={"question": "q"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail == meeting_ask.LLM_UNAVAILABLE
    assert "test-key" not in r.text and "http" not in detail


async def test_desktop_ask_no_api_key_503(sm, client, monkeypatch):
    async def _no_keys():
        return {}

    monkeypatch.setattr(meeting_ask, "load_api_keys", _no_keys)
    token = await _device(sm, await _user(sm))
    mid = (await _meeting(client, token))["meeting_id"]
    r = await client.post(f"/api/desktop/meetings/{mid}/ask", headers=_bearer(token),
                          json={"question": "q"})
    assert r.status_code == 503


# ---------- сайт ----------

async def test_web_ask_ok_and_prompt_has_context(sm, client):
    user = await _user(sm)
    token = await _device(sm, user)
    mid = await _prepare(sm, client, token)
    r = await client.post(f"/api/meetings/{mid}/ask", headers=_jwt(user),
                          json={"question": "что обещали по срокам?"})
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"answer", "sources"}
    assert "Срок сдачи фасада сдвигаем на март" in _FakeLLM.prompts[-1]


async def test_web_ask_missing_meeting_404_and_forbidden_403(sm, client, monkeypatch):
    user = await _user(sm)
    r = await client.post("/api/meetings/9999/ask", headers=_jwt(user), json={"question": "q"})
    assert r.status_code == 404

    token = await _device(sm, user)
    mid = (await _meeting(client, token))["meeting_id"]

    async def _deny(db, user_id, meeting_id):
        return False

    from app.api import meeting_ask as api_mod
    monkeypatch.setattr(api_mod, "user_can_access_meeting", _deny)
    r = await client.post(f"/api/meetings/{mid}/ask", headers=_jwt(user), json={"question": "q"})
    assert r.status_code == 403
    assert _FakeLLM.prompts == []


async def test_web_ask_requires_auth_and_validates(sm, client):
    r = await client.post("/api/meetings/1/ask", json={"question": "q"})
    assert r.status_code in (401, 403)
    user = await _user(sm)
    r = await client.post("/api/meetings/1/ask", headers=_jwt(user), json={"question": ""})
    assert r.status_code == 422


# ---------- контекст ----------

async def test_context_limit_and_previous_meetings_same_customer(sm):
    from app.models.directory import Customer
    from app.models.user import User

    async with sm() as db:
        user = User(email="u@t.local", password_hash="x", role="user", is_active=True)
        cust = Customer(name="ООО Заказчик")
        db.add_all([user, cust])
        await db.flush()
        prev = MeetingSession(user_id=user.id, title="Прошлая планерка", customer_id=cust.id,
                              status="finalized", is_active=False, finalization_status="completed",
                              micro_summary="Договорились о сроках сдачи фасада",
                              started_at=datetime(2026, 9, 1, 10, 0))
        cur = MeetingSession(user_id=user.id, title="Текущая", customer_id=cust.id,
                             started_at=datetime(2026, 10, 1, 10, 0))
        db.add_all([prev, cur])
        await db.flush()

        context, sources = await meeting_ask._build_context(db, user, cur, "сроки", {})

    assert "Договорились о сроках сдачи фасада" in context
    assert {"kind": "meeting", "title": "Прошлая планерка", "ref": "01.09.2026"} in sources
    assert len(context) < meeting_ask.MAX_CONTEXT_CHARS + 2000


def test_fit_truncates_transcript_head_and_total():
    big = meeting_ask._Section("transcript", "Т", "а" * 50000,
                               [(None, meeting_ask._src("transcript", "Т"))])
    fitted = meeting_ask._fit([big])
    assert len(fitted[0].text) <= meeting_ask.SECTION_CAPS["transcript"] + 1
    assert fitted[0].text.startswith("…")


# ---------- заметки в протоколе ----------

def test_protocol_prompt_has_notes_block_only_when_notes():
    with_notes = build_user_prompt("Заказчик: ООО", "[00:01] Мы: привет", "",
                                   meeting_notes="[00:05] договорились о сроке до 1 марта")
    assert "КЛЮЧЕВЫЕ УСЛОВИЯ И ЦЕЛИ УЧАСТНИКА" in with_notes
    assert "[00:05] договорились о сроке до 1 марта" in with_notes
    assert "приоритетные акценты" in with_notes
    assert "ЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ" not in with_notes

    for empty in ("", "   ", None):
        without = build_user_prompt("Заказчик: ООО", "[00:01] Мы: привет", "",
                                    meeting_notes=empty or "", app_notes=empty or "")
        assert "КЛЮЧЕВЫЕ УСЛОВИЯ" not in without
        assert "ЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ" not in without
        assert "приоритетные акценты" not in without


def test_protocol_prompt_has_separate_blocks_for_key_terms_and_app_notes():
    p = build_user_prompt("Заказчик: ООО", "[00:01] Мы: привет", "",
                          meeting_notes="Аванс не более 30%", app_notes="[00:05] срок до 1 марта")
    assert "===== КЛЮЧЕВЫЕ УСЛОВИЯ И ЦЕЛИ УЧАСТНИКА =====\nАванс не более 30%" in p
    assert "===== ЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ (строки с [мм:сс] — сделаны во время встречи) =====\n[00:05] срок до 1 марта" in p
    assert p.index("Аванс не более 30%") < p.index("[00:05] срок до 1 марта")

    only_app = build_user_prompt("Заказчик: ООО", "т", "", app_notes="[00:05] срок")
    assert "ЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ" in only_app and "КЛЮЧЕВЫЕ УСЛОВИЯ" not in only_app


async def test_gather_inputs_does_not_duplicate_notes(db):
    m = MeetingSession(title="t", meeting_notes="[00:05] заметка", status="finalized",
                       started_at=datetime(2026, 1, 1, 10, 0))
    db.add(m)
    await db.flush()
    block, _t, _d, _n = await _gather_inputs(db, m)
    assert "заметка" not in block
