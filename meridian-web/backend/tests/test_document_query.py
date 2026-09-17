# -*- coding: utf-8 -*-
"""Переформулировка реплики в язык договора перед поиском по документам."""

import asyncio

from app.config import get_settings
from app.services.document_query import build_expansion_prompt, parse_expansion
from app.services.session_manager import SessionManager


def test_parse_expansion_strips_markup_and_limits_length():
    raw = "**Формулировки:**\n1. гарантийное удержание\n- компенсация затрат\n* продление сроков"
    assert parse_expansion(raw) == "Формулировки:; гарантийное удержание; компенсация затрат; продление сроков"
    assert len(parse_expansion("термин; " * 200)) <= 600
    assert parse_expansion(None) == ""


def test_prompt_uses_last_replicas():
    dialog = "начало встречи " * 300 + "Заказчик: начислим неустойку с завтрашнего дня"
    prompt = build_expansion_prompt(dialog)
    assert prompt.endswith("Заказчик: начислим неустойку с завтрашнего дня")
    assert "начало встречи " * 100 not in prompt


class _Llm:
    def __init__(self, answer, delay=0.0):
        self.answer, self.delay, self.calls = answer, delay, 0

    async def get_suggestion_async(self, prompt, max_tokens=None):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return self.answer


async def test_terms_are_passed_to_provider_and_cached():
    sm = SessionManager(1)
    sm.db_session_id = 7
    sm.llm_client = _Llm("компенсация затрат; продление сроков")
    seen = []

    async def provider(mid, q, extra=""):
        seen.append((mid, q, extra))
        return "DOC"

    sm.set_doc_context_provider(provider)
    await sm._augment_doc_context("", "Заказчик: срок сдвигаем", expand_query=True)
    await sm._augment_doc_context("", "Заказчик: срок сдвигаем", expand_query=True)
    assert seen[0] == (7, "Заказчик: срок сдвигаем", "компенсация затрат; продление сроков")
    assert sm.llm_client.calls == 1


async def test_slow_model_falls_back_to_plain_search(monkeypatch):
    monkeypatch.setattr(get_settings(), "document_query_expansion_timeout_seconds", 0.05)
    sm = SessionManager(1)
    sm.db_session_id = 7
    sm.llm_client = _Llm("компенсация затрат", delay=1.0)
    seen = []

    async def provider(mid, q):
        seen.append(q)
        return "DOC"

    sm.set_doc_context_provider(provider)
    assert await sm._augment_doc_context("", "Заказчик: срок сдвигаем", expand_query=True) == "DOC"
    assert seen == ["Заказчик: срок сдвигаем"]


async def test_expansion_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "document_query_expansion_enabled", False)
    sm = SessionManager(1)
    sm.llm_client = _Llm("термины")
    assert await sm._doc_query_terms("Заказчик: срок сдвигаем") == ""
    assert sm.llm_client.calls == 0


async def test_auto_path_does_not_expand_by_default():
    """Авто-подсказки ищут по документам на каждой пачке реплик — без лишнего вызова модели."""
    sm = SessionManager(1)
    sm.db_session_id = 7
    sm.llm_client = _Llm("компенсация затрат")
    seen = []

    async def provider(mid, q, extra=""):
        seen.append(extra)
        return "DOC"

    sm.set_doc_context_provider(provider)
    await sm._build_context_pack_for_prompt(mode="auto", query_text="Заказчик: срок сдвигаем",
                                            meeting_context_block="")
    assert seen == [""] and sm.llm_client.calls == 0
    await sm._build_context_pack_for_prompt(mode="manual", query_text="Заказчик: срок сдвигаем",
                                            meeting_context_block="")
    assert seen[-1] == "компенсация затрат" and sm.llm_client.calls == 1
