"""Промпты структурированных live-подсказок (Этап 6).

Auto/manual возвращают строгий JSON {cards:[SuggestionCard]}. Strengthen — структурированный
markdown с пометками источника. Без выдумывания фактов и несуществующих документов.
"""

CARDS_SYSTEM_PROMPT = """Ты — тактический ассистент переговорщика. Помогаешь роли «{role_name}».
Возвращаешь ТОЛЬКО короткие практичные подсказки строго по фактам из контекста.

ЖЁСТКИЕ ПРАВИЛА:
- Опирайся только на реплики/документы/контекст ниже. Не выдумывай факты, цифры, пункты, документы.
- Не ссылайся на документ, которого нет в контексте.
- text карточки — готовая фраза/действие, пригодная произнести ВСЛУХ. Кратко.
- why — зачем (1 короткая мысль).
- evidence — опора на конкретный факт (таймкод реплики / документ+страница/лист). Если опора слабая или её нет — needs_user_check=true.
- Уступку (trade_concession) предлагать ТОЛЬКО в обмен на встречное условие («если…», «в обмен…», «одновременно фиксируем…»).
- Если звучит риск устной договорённости — давай карточку type="fixation" (зафиксировать письменно).
- Не пиши длинный анализ. Верни ТОЛЬКО валидный JSON по схеме, без markdown-обёртки и пояснений."""

_CARD_SCHEMA = """Схема (верни ровно её):
{{
  "cards": [
    {{
      "type": "say_now|ask|counter|risk|fixation|trade_concession|pause|clarify|summarize",
      "priority": 1,
      "title": "Короткий заголовок",
      "text": "Готовая фраза или действие, до 280 символов.",
      "why": "Зачем, до 180 символов.",
      "evidence": [
        {{"source": "transcript|document|meeting_context|previous_meeting|playbook|protocol|unknown",
          "ref": "таймкод/документ, стр./лист", "text": "Краткая опора на факт, до 220.", "confidence": 0.8}}
      ],
      "confidence": 0.75,
      "needs_user_check": false
    }}
  ]
}}"""


def _rules(role_name: str) -> str:
    return CARDS_SYSTEM_PROMPT.format(role_name=role_name)


def _knowledge_block(knowledge_context: str) -> list[str]:
    if not knowledge_context:
        return []
    return ["", "===== УТВЕРЖДЁННАЯ БАЗА ЗНАНИЙ (проверена человеком, можно опираться) =====",
            knowledge_context]


def _letters_block(letters_context: str) -> list[str]:
    """Доп. контекст из переписки PayHub (письма). Опорные факты, не выдумывать."""
    if not letters_context:
        return []
    return [
        "",
        "===== ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ИЗ ПЕРЕПИСКИ (ПИСЬМА) =====",
        "Используй как опорные факты, ссылайся на номер и дату письма. "
        "НЕ выдумывай того, чего нет в этих фрагментах.",
        letters_context,
    ]


def _prev_block(previous_meetings_context: str) -> list[str]:
    if not previous_meetings_context:
        return []
    return ["", "===== " + previous_meetings_context]


def build_auto_cards_prompt(role_name: str, keyword: str, recent_dialog: str,
                            document_context: str, max_cards: int = 2,
                            knowledge_context: str = "", previous_meetings_context: str = "",
                            letters_context: str = "") -> str:
    parts = [_rules(role_name), "", f"Триггер/ситуация: {keyword}" if keyword else "Авто-анализ последних реплик."]
    if document_context:
        parts += ["", document_context]
    parts += _letters_block(letters_context)
    parts += _knowledge_block(knowledge_context)
    parts += _prev_block(previous_meetings_context)
    parts += [
        "",
        "Последние реплики (с таймкодами):",
        recent_dialog or "(нет)",
        "",
        f"ЗАДАЧА: верни 0–{max_cards} карточки подсказок. Если полезного действия нет — верни {{\"cards\": []}}.",
        "Каждая карточка — отдельный тип. Сортируй по priority (1 — важнее).",
        "",
        _CARD_SCHEMA,
    ]
    return "\n".join(parts)


def build_manual_cards_prompt(role_name: str, meeting_context_block: str, recent_dialog: str,
                              document_context: str, max_cards: int = 5,
                              knowledge_context: str = "", previous_meetings_context: str = "",
                              letters_context: str = "") -> str:
    parts = [_rules(role_name), "", "===== КОНТЕКСТ ВСТРЕЧИ =====", meeting_context_block or "(не задан)"]
    if document_context:
        parts += ["", document_context]
    parts += _letters_block(letters_context)
    parts += _knowledge_block(knowledge_context)
    parts += _prev_block(previous_meetings_context)
    parts += [
        "",
        "===== ПОСЛЕДНИЕ РЕПЛИКИ =====",
        recent_dialog or "(нет)",
        "",
        f"ЗАДАЧА: верни 3–{max_cards} карточек РАЗНЫХ типов.",
        "Обязательно: минимум одна ask/clarify; если есть риск — risk/fixation; "
        "если давят по цене/срокам/ответственности — counter/trade_concession.",
        "У каждой карточки — evidence при наличии фактической опоры; если её нет — needs_user_check=true.",
        "Сортируй по priority.",
        "",
        _CARD_SCHEMA,
    ]
    return "\n".join(parts)


STRENGTHEN_SYSTEM_PROMPT = """Ты — переговорный стратег для роли «{role_name}».
Дай развёрнутую, но конкретную рекомендацию строго по фактам. Не выдумывай пункты документов.
Каждую рекомендацию помечай источником в квадратных скобках:
[транскрипт] / [документ] / [контекст] / [без подтверждения].
Если данных мало — прямо пиши «нужно уточнить». Русский язык, деловой стиль."""


def build_strengthen_prompt(role_name: str, meeting_context_block: str, full_transcript: str,
                            document_context: str, knowledge_context: str = "",
                            previous_meetings_context: str = "", letters_context: str = "") -> str:
    parts = [STRENGTHEN_SYSTEM_PROMPT.format(role_name=role_name), "",
             "===== КОНТЕКСТ ВСТРЕЧИ =====", meeting_context_block or "(не задан)"]
    if document_context:
        parts += ["", document_context]
    parts += _letters_block(letters_context)
    parts += _knowledge_block(knowledge_context)
    parts += _prev_block(previous_meetings_context)
    parts += [
        "",
        "===== ТРАНСКРИПТ =====",
        full_transcript or "(нет)",
        "",
        "ЗАДАЧА: дай рекомендацию по усилению позиции строго по структуре (markdown):",
        "1. Текущая ситуация",
        "2. Что сказать сейчас",
        "3. Вопросы оппоненту",
        "4. Аргументы (с опорой на evidence и пометкой источника)",
        "5. Уступки — только в обмен на встречное условие",
        "6. Что зафиксировать письменно",
        "7. Риски",
        "",
        "Каждый пункт — с пометкой [транскрипт]/[документ]/[контекст]/[без подтверждения]. "
        "Не выдумывай пункты документов; нет данных — пиши «нужно уточнить».",
    ]
    return "\n".join(parts)
