# -*- coding: utf-8 -*-
"""Протокол из тишины: меньше MIN_PROTOCOL_WORDS слов речи — без LLM; правило промпта; пустой контекст прошлых встреч."""

import json

from app.core.llm.finalization_prompt import SYSTEM_PROMPT
from app.models.context_source import MeetingContextSource
from app.models.meeting import MeetingSession
from app.models.protocol import MeetingDecision
from app.services import meeting_finalize as mf
from app.services.previous_meeting_context import build_previous_context_block

from .test_stage5_finalization import (  # noqa: F401
    FAKE_RESULT, FakeLLM, SPEECH, _add_segment, _mk_meeting, _mk_user, _patch_llm, sqlite_sm,
)
from .test_stage8_context import _mk_meeting as _mk_prev_meeting


def test_count_speech_words_ignores_service_text():
    text = (
        "[00:01] Мы: [шум]\n"
        "[00:05] Голос 2 (оппонент): (музыка) да 123 ок\n"
        "[00:09] Оппонент: Добрый день, коллеги"
    )
    # «да», «ок», «Добрый», «день», «коллеги»; подписи, таймкоды, метки и цифры не считаются
    assert mf.count_speech_words(text) == 5
    assert mf.count_speech_words("") == 0
    assert mf.MIN_PROTOCOL_WORDS == 20


async def test_silence_meeting_skips_llm(sqlite_sm, monkeypatch):
    calls = []

    class SpyLLM(FakeLLM):
        async def get_suggestion_async(self, prompt, max_tokens=None):
            calls.append(prompt)
            return json.dumps(FAKE_RESULT, ensure_ascii=False)

    _patch_llm(monkeypatch, SpyLLM)
    async with sqlite_sm() as db:
        owner = await _mk_user(db, "silence1@test.local")
        meeting = await _mk_meeting(db, owner)
        await _add_segment(db, meeting, "[шум]", 0)
        await _add_segment(db, meeting, "Алло, да, слышно плохо", 1)  # 4 слова
        await db.commit()
        mid = meeting.id

    await mf.handle_meeting_finalize({"meeting_id": mid})

    assert calls == []
    async with sqlite_sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.finalization_status == "partial"
        assert m.finalization_error == "Речь не распознана — протокол не составлен"
        assert m.protocol_markdown is None and m.protocol_json is None
        assert m.is_finalized is True


async def test_enough_words_builds_protocol(sqlite_sm, monkeypatch):
    _patch_llm(monkeypatch)
    async with sqlite_sm() as db:
        owner = await _mk_user(db, "silence2@test.local")
        meeting = await _mk_meeting(db, owner)
        await _add_segment(db, meeting, "Обсуждаем цену." + SPEECH, 0)
        await db.commit()
        mid = meeting.id

    await mf.handle_meeting_finalize({"meeting_id": mid})

    async with sqlite_sm() as db:
        m = await db.get(MeetingSession, mid)
        assert m.finalization_status == "completed" and m.protocol_markdown


def test_prompt_says_transcript_only():
    assert "только из транскрипта" in SYSTEM_PROMPT
    assert "не выдавай их содержание за то, что обсуждалось на встрече" in SYSTEM_PROMPT


async def test_previous_context_skips_meeting_without_protocol(db):
    owner = await _mk_user(db, "silence3@test.local")
    cur = await _mk_prev_meeting(db, owner, active=True, finalized=False)
    silent = await _mk_prev_meeting(db, owner, day=2, title="Тишина")
    silent.protocol_markdown = None
    silent.finalization_status = "partial"
    silent.micro_summary = "Нет транскрипта для протокола"
    real = await _mk_prev_meeting(db, owner, day=3, title="С протоколом")
    for prev in (silent, real):
        db.add(MeetingContextSource(meeting_id=cur.id, source_type="previous_meeting",
                                    source_id=prev.id, included=True))
    await db.flush()

    block = await build_previous_context_block(db, cur.id, viewer_user_id=owner.id)
    assert "С протоколом" in block and "Тишина" not in block

    # единственная встреча без протокола — блока нет вовсе
    real.protocol_markdown = None
    await db.flush()
    assert await build_previous_context_block(db, cur.id, viewer_user_id=owner.id) == ""

    # решения в структурных таблицах считаются содержимым, даже без markdown
    db.add(MeetingDecision(meeting_id=real.id, text="Согласовать цену", status="accepted"))
    await db.flush()
    assert "Согласовать цену" in await build_previous_context_block(db, cur.id, viewer_user_id=owner.id)
