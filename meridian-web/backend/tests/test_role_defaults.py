# -*- coding: utf-8 -*-
"""Роль по умолчанию не должна запрещать конкретику.

В custom_instructions роли стояло «Давай только общие рекомендации». Эта строка уходит
в системный промпт ПОВЕРХ промпта карточек, который требует готовую фразу с опорой на
пункт документа. Два указания противоречили друг другу, побеждало общее — отсюда
обтекаемые подсказки на реальных переговорах.

Тесты стерегут именно формулировку: правка промптов карточек ничего не даст, если роль
снова начнёт просить «общие рекомендации».
"""

import pytest

from app.api.roles import DEFAULT_ROLE
from app.core.context.knowledge_base import CONSTRUCTION_KNOWLEDGE, get_terms_glossary
from app.core.llm.prompts import DEFAULT_ROLE_DATA, PromptBuilder

# Формулировки, которые обязаны быть в инструкциях роли (по одному ключевому слову на правило).
REQUIRED_RULES = [
    "готовую фразу",       # конкретика вместо теории
    "опора",               # ссылаться на источник
    "не выдумывай",        # запрет на вымышленные пункты — он был правильным
    "в обмен",             # уступка только за встречное условие
    "письменно",           # фиксация договорённостей
    "слабую позицию",      # не раскрывать свои запасы
]


def test_default_role_is_single_source():
    """Раньше словарь был скопирован в api/roles.py и в prompts.py — копии разъехались."""
    assert DEFAULT_ROLE is DEFAULT_ROLE_DATA


def test_default_role_has_fields_expected_by_model():
    """api/roles.py передаёт словарь в NegotiationRole(**DEFAULT_ROLE)."""
    assert set(DEFAULT_ROLE) == {
        "name", "description", "interests", "opponents", "custom_instructions",
    }
    assert all(str(v).strip() for v in DEFAULT_ROLE.values())


def test_role_does_not_demand_generic_advice():
    ci = DEFAULT_ROLE_DATA["custom_instructions"].lower()
    assert "общие рекомендации" not in ci
    assert "только общие" not in ci


@pytest.mark.parametrize("rule", REQUIRED_RULES)
def test_role_keeps_negotiation_discipline(rule):
    assert rule.lower() in DEFAULT_ROLE_DATA["custom_instructions"].lower()


def test_instructions_reach_the_system_prompt():
    """Инструкции — не мёртвая константа: они должны доезжать до системного промпта."""
    prompt = PromptBuilder().system_prompt
    assert DEFAULT_ROLE_DATA["custom_instructions"] in prompt
    assert DEFAULT_ROLE_DATA["interests"] in prompt
    assert DEFAULT_ROLE_DATA["opponents"] in prompt


def test_custom_role_overrides_defaults_in_system_prompt():
    """Своя роль пользователя вытесняет дефолт целиком, а не смешивается с ним."""
    prompt = PromptBuilder(role_data={
        "name": "Заказчик",
        "description": "Девелопер",
        "interests": "Снижение стоимости",
        "opponents": "Генподрядчики",
        "custom_instructions": "Своя инструкция.",
    }).system_prompt
    assert "Своя инструкция." in prompt
    assert DEFAULT_ROLE_DATA["custom_instructions"] not in prompt


# --- глоссарий, который подставляется в системный промпт ---

def test_ird_definition_is_correct():
    """ИРД — исходно-разрешительная документация; исполнительная — это ИД."""
    assert CONSTRUCTION_KNOWLEDGE["terms"]["ИРД"] == "Исходно-разрешительная документация"


def test_id_is_a_separate_term():
    """«Грейс-период по ИД» звучит на реальных встречах — термин должен быть отдельным."""
    assert CONSTRUCTION_KNOWLEDGE["terms"]["ИД"] == "Исполнительная документация"


def test_glossary_reaches_the_system_prompt():
    glossary = get_terms_glossary()
    assert "ИД: Исполнительная документация" in glossary
    assert "Исполнительная рабочая документация" not in glossary
    assert glossary in PromptBuilder().system_prompt
