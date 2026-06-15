"""Промпт извлечения кандидатов для базы знаний (Этап 7).

LLM возвращает строго JSON {"candidates": [...]}. Кандидаты НЕ применяются автоматически —
только после ручного approve. Без выдумывания, без чувствительных персональных данных.
"""

SYSTEM_PROMPT = """Ты — аналитик базы знаний переговоров. По завершённой встрече предлагаешь
КАНДИДАТОВ для базы знаний: термины, триггерные фразы, playbooks, особенности заказчика,
нежелательные/рискованные формулировки. Это ПРЕДЛОЖЕНИЯ для ручной проверки человеком.

ЖЁСТКИЕ ПРАВИЛА:
- Опирайся ТОЛЬКО на факты встречи (транскрипт/протокол/документы). Не выдумывай.
- Каждому кандидату нужен source_text (короткая дословная опора).
- Не предлагай общеупотребительные слова и банальности.
- Не делай вывод об особенности заказчика по одной слабой реплике — нужна явная опора.
- НЕ сохраняй чувствительные персональные данные (здоровье, религия, политика, национальность и т.п.).
- Не превращай ошибку распознавания речи в термин.
- Не дублируй уже утверждённые знания (список ниже).
- Если полезных кандидатов нет — верни {"candidates": []}.
- Максимум кандидатов — указан в задаче. Все тексты на русском.
- Верни ТОЛЬКО валидный JSON по схеме, без markdown-обёртки."""

_SCHEMA = """Схема ответа:
{{
  "candidates": [
    {{
      "candidate_type": "term|trigger_phrase|playbook|counterparty_trait|forbidden_phrase",
      "title": "Короткий заголовок",
      "confidence": 0.75,
      "source_text": "короткая цитата/фрагмент (обязательно)",
      "source_refs": [{{"type": "transcript|protocol|document|decision|risk|action_item", "ref": "...", "text": "..."}}],
      "payload": {{}}
    }}
  ]
}}
payload по типам:
- term: {{"term":"...","definition":"...","aliases":["..."],"scope":"global|customer|object"}}
- trigger_phrase: {{"phrase":"...","event_type":"price_pressure|deadline_pressure|liability_shift|concession_request|fixation_request|stalling|contradiction_signal|other","recommended_reaction":"...","scope":"global|customer|object"}}
- playbook: {{"situation":"...","recommended_phrase":"...","technique":"conditional_concession|calibrated_question|fixation|reframing|risk_transfer_block|other","ask_in_return":["..."],"risks":["..."],"scope":"global|customer|object"}}
- counterparty_trait: {{"trait":"...","evidence":"...","recommended_strategy":"...","scope":"customer|object"}}
- forbidden_phrase: {{"phrase_or_risk":"...","better_alternative":"...","reason":"...","scope":"global|customer|object"}}"""


def build_user_prompt(meeting_block: str, protocol_block: str, transcript_excerpt: str,
                      existing_knowledge_block: str, max_candidates: int) -> str:
    parts = ["===== КОНТЕКСТ ВСТРЕЧИ =====", meeting_block or "(нет)"]
    if protocol_block:
        parts += ["", "===== ПРОТОКОЛ =====", protocol_block]
    if existing_knowledge_block:
        parts += ["", "===== УЖЕ УТВЕРЖДЁННЫЕ ЗНАНИЯ (не дублируй) =====", existing_knowledge_block]
    parts += [
        "", "===== ТРАНСКРИПТ (фрагменты) =====", transcript_excerpt or "(нет)",
        "",
        f"ЗАДАЧА: предложи до {max_candidates} кандидатов для базы знаний строго по фактам. "
        "Если полезного нет — {\"candidates\": []}.",
        "", _SCHEMA,
    ]
    return "\n".join(parts)


def build_repair_prompt(broken: str) -> str:
    return ("Преобразуй ответ в ОДИН валидный JSON-объект {\"candidates\":[...]} по схеме. "
            "Верни ТОЛЬКО JSON:\n\n" + (broken or "")[:12000])
