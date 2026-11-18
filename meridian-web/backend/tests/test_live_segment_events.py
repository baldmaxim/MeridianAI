# -*- coding: utf-8 -*-
"""Живая встреча: язык, перевод и метка говорящего у committed-реплики (WS-сообщения)."""

import asyncio

from app.core.transcription.models import CommittedSegment
from app.services import live_translation
from app.services.live_translation import segment_needs_translation
from app.services.session_manager import SessionManager


def _seg(text, language=None):
    return CommittedSegment(text=text, language=language)


def test_needs_translation_by_language_then_by_text():
    assert segment_needs_translation(_seg("merhaba", "tr"))
    assert segment_needs_translation(_seg("hello", "eng"))
    assert not segment_needs_translation(_seg("привет", "ru"))
    assert not segment_needs_translation(_seg("привет", "RU"))
    assert not segment_needs_translation(_seg("привет"))        # язык неизвестен → кириллица
    assert segment_needs_translation(_seg("Evet, tamam."))       # язык неизвестен → не кириллица


async def _collect(sm, count, timeout=3.0):
    sent = []

    async def send(data):
        sent.append(data)

    sm.set_ws_send(send)
    return sent, send


async def test_committed_sends_language_and_translation(monkeypatch):
    class FakeTranslator:
        def __init__(self, key):
            assert key == "or-key"

        async def translate(self, texts):
            return {0: "Здравствуйте"}

    monkeypatch.setattr(live_translation, "SegmentTranslator", FakeTranslator)
    sm = SessionManager(1)
    sm._llm_api_key = "or-key"
    sent, _ = await _collect(sm, 2)

    seg = _seg("Merhaba", "tr")
    sm._on_committed(seg)
    await _until(lambda: any(m["type"] == "segment_translation" for m in sent))

    committed = next(m for m in sent if m["type"] == "committed_transcript")
    assert committed["language"] == "tr" and committed["segment_id"] == seg.segment_id
    turn = next(m for m in sent if m["type"] == "turn_update")
    assert turn["segment_ids"] == [seg.segment_id]
    tr = next(m for m in sent if m["type"] == "segment_translation")
    assert tr == {"type": "segment_translation", "segment_id": seg.segment_id, "text": "Здравствуйте"}


async def test_translation_skipped_without_key_and_for_russian(monkeypatch):
    calls = []

    class FakeTranslator:
        def __init__(self, key):
            calls.append(key)

        async def translate(self, texts):
            return {0: "x"}

    monkeypatch.setattr(live_translation, "SegmentTranslator", FakeTranslator)
    sm = SessionManager(1)
    sent, _ = await _collect(sm, 1)
    sm._on_committed(_seg("Merhaba", "tr"))        # нет ключа
    sm._llm_api_key = "k"
    sm._on_committed(_seg("Привет", "ru"))         # русская
    sm._on_committed(_seg("Merhaba", "tr"), replay=True)  # досыпка истории
    await asyncio.sleep(0.1)
    assert calls == [] and not any(m["type"] == "segment_translation" for m in sent)


async def test_segment_speaker_message_keeps_speaker_id():
    sm = SessionManager(1)
    sent, _ = await _collect(sm, 1)
    seg = _seg("Привет")
    sm._on_segment_speaker(seg, "s1_speaker_0")
    await asyncio.sleep(0.05)
    assert sent == [{"type": "segment_speaker", "segment_id": seg.segment_id, "speaker": "s1_speaker_0"}]
    assert seg.diarized_speaker == "s1_speaker_0" and seg.speaker_id == "unknown_speaker"


async def _until(cond, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < end, "таймаут"
        await asyncio.sleep(0.02)
