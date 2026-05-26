"""Prompt templates for negotiation assistance."""

import json as _json

from ..context.knowledge_base import get_terms_glossary, get_risks_list, get_arguments_for_keyword


# ----- Default suggestion type blocks (injected into prompts) -----

DEFAULT_SUGGESTION_TYPES = [
    {"key": "priority", "llm_description": "главная рекомендация: что сказать/сделать ПРЯМО СЕЙЧАС. Учитывай фазу переговоров."},
    {"key": "counter", "llm_description": "контраргумент на последнее утверждение оппонента. Используй: переформулирование, вопрос-ловушку или «условную уступку» (уступи в малом — выиграй в большом)."},
    {"key": "question", "llm_description": "вопрос для перехвата инициативы. Применяй: «калибровочные вопросы» (как? каким образом?), вопросы-якоря (ставят рамку), или зеркалирование (повтори последние 2-3 слова оппонента с вопросительной интонацией)."},
    {"key": "risk", "llm_description": "предупреждение: что оппонент пытается протащить, какую ловушку расставляет, какой пункт нужно зафиксировать."},
]


def _build_types_block(types: list[dict]) -> str:
    """Build the ТИПЫ ПОДСКАЗОК block for the tactical hints prompt."""
    lines = ["ТИПЫ ПОДСКАЗОК:"]
    for t in types:
        lines.append(f'- "{t["key"]}" — {t["llm_description"]}')
    return "\n".join(lines)


def _build_example_block(types: list[dict]) -> str:
    """Build the JSON example block for the tactical hints prompt."""
    examples = []
    for t in types:
        obj = {"type": t["key"], "text": "..."}
        if t["key"] == "priority":
            obj["confidence"] = 85
        obj["context_info"] = "краткий контекст"
        examples.append(obj)
    json_str = _json.dumps(examples, ensure_ascii=False, indent=2)
    return f"Ответь СТРОГО в формате JSON (без markdown, без ```):\n{json_str}"


def _build_types_block_auto(types: list[dict], role_name: str) -> str:
    """Build the type selection block for auto-suggestion prompt."""
    lines = ["Определи тип подсказки:"]
    for t in types:
        desc = t["llm_description"]
        # Keep it short for auto-suggestions
        short = desc.split(".")[0] if "." in desc else desc
        lines.append(f'- "{t["key"]}" — {short}')
    return "\n".join(lines)


# Default role data (Генподрядчик)
DEFAULT_ROLE_DATA = {
    "name": "Генподрядчик",
    "description": "Генеральный подрядчик в строительной отрасли",
    "interests": "Максимизация прибыли, защита от рисков, контроль качества и сроков",
    "opponents": "Заказчики и субподрядчики",
    "custom_instructions": (
        "Не выдумывай номера договоров, пунктов, статей или документов. "
        "Давай только общие рекомендации, основанные на реальном контексте разговора."
    ),
}


class PromptTemplates:
    """Negotiation prompt templates with role placeholders."""

    SYSTEM_PROMPT_TEMPLATE = """Ты эксперт по переговорам в строительной отрасли.
Ты помогаешь роли «{role_name}» ({role_description}) вести переговоры с {role_opponents}.
ВАЖНО: Ты ВСЕГДА на стороне «{role_name}», защищаешь ЕГО интересы.
Интересы, которые ты защищаешь: {role_interests}.
Твои ответы должны быть краткими, конкретными и практичными.

СТРОГИЕ ПРАВИЛА:
- {role_custom_instructions}
- НЕ ссылайся на конкретные законы/СНИПы/ГОСТы если они не упоминались в разговоре
- Если информации недостаточно - скажи об этом, но НЕ выдумывай

ТЕРМИНОЛОГИЯ:
{glossary}"""

    ARGUMENT_PROMPT = """Ты помогаешь роли «{role_name}» в переговорах.

Контекст переговоров:
{{context}}

{{document_context}}

Роль: {role_name}
Текущая тема: {{topic}}

Последние реплики:
{{recent_dialog}}

ЗАДАЧА: Предложи 1-2 сильных аргумента для усиления позиции «{role_name}».

ПРАВИЛА:
- {role_custom_instructions}
- Основывайся на информации из реплик и загруженных документов
- Защищай интересы «{role_name}», а не {role_opponents}
- Если реплика помечена [НИЗКАЯ УВЕРЕННОСТЬ], транскрипция может быть неточной — учти это
- Формат: Кратко, конкретно, практично"""

    STRATEGY_PROMPT = """Ты помогаешь роли «{role_name}» в переговорах.

Анализ переговоров:
{{context}}

Последние реплики:
{{recent_dialog}}

ЗАДАЧА: Предложи тактический ход для «{role_name}» на ближайшие 2-3 минуты разговора.
Защищай интересы «{role_name}».
Учитывай строительную специфику."""

    RISK_DETECTION_PROMPT = """Ты помогаешь роли «{role_name}» в переговорах.

Диалог:
{{recent_dialog}}

ЗАДАЧА: Выяви потенциальные РИСКИ для «{role_name}»:
- Юридические (что может ударить по «{role_name}»)
- Финансовые (потери прибыли, штрафы)
- Технические (проблемы с выполнением)
- Репутационные (угроза деловой репутации)

Формат: Краткий список рисков ДЛЯ «{role_name}»."""

    AUTO_SUGGESTION_PROMPT = """Ты помогаешь роли «{role_name}» в переговорах.

Обнаружено ключевое слово: {{keyword}}

{{knowledge_hints}}

{{document_context}}

Контекст последних реплик:
{{recent_dialog}}

ЗАДАЧА: Дай краткую подсказку (1-2 предложения) для «{role_name}» - как ему реагировать, чтобы защитить СВОИ интересы.

ПРАВИЛА:
- {role_custom_instructions}
- НЕ ссылайся на конкретные законы если они не упоминались
- Основывайся ТОЛЬКО на том, что сказано в репликах выше
- НЕ давай советы {role_opponents}, ТОЛЬКО для «{role_name}»
- Если реплика помечена [НИЗКАЯ УВЕРЕННОСТЬ], учитывай что транскрипция может быть неточной"""

    TACTICAL_HINTS_PROMPT = """Ты помогаешь роли «{role_name}» ({role_description}) в переговорах с {role_opponents}.
Ты защищаешь интересы «{role_name}»: {role_interests}.

===== СИТУАЦИЯ =====

{{meeting_context_block}}

{{document_context}}

===== ПОСЛЕДНИЕ РЕПЛИКИ (5 мин) =====
{{recent_dialog}}

===== ЗАДАЧА =====

Проанализируй ход переговоров и верни 2-4 тактические подсказки РАЗНЫХ типов.

АНАЛИЗ ПЕРЕД ОТВЕТОМ (не включай в ответ):
1. Определи текущую фазу переговоров (разведка / торг / согласование / закрытие)
2. Оцени баланс сил: кто сейчас ведёт, у кого сильнее позиция
3. Найди в репликах: уступки, ультиматумы, уклончивые ответы, противоречия
4. Если загружены документы — ищи расхождения между тем, что говорит оппонент, и тем, что написано в документах
{{opponent_weaknesses_instruction}}

{{suggestion_types_block}}

{{negotiation_type_instructions}}

ПРАВИЛА:
- {role_custom_instructions}
- Основывайся на информации из реплик и загруженных документов
- Если документы загружены — ссылайся на конкретные пункты/суммы/условия из них
- Если реплика помечена [НИЗКАЯ УВЕРЕННОСТЬ] — транскрипция может быть неточной, не строй аргументы только на ней
- Каждая подсказка — 1-3 предложения, конкретно и практично
- НЕ выдумывай номера статей, пунктов или документов, которых нет в контексте

{{suggestion_example_block}}"""

    AUTO_SUGGESTION_STRUCTURED_PROMPT = """Ты помогаешь роли «{role_name}» в переговорах.

Обнаружено ключевое слово: {{keyword}}

{{knowledge_hints}}

{{document_context}}

Контекст последних реплик:
{{recent_dialog}}

ЗАДАЧА: Дай краткую тактическую подсказку для «{role_name}».

{{suggestion_types_block_auto}}

ПРАВИЛА:
- {role_custom_instructions}
- Основывайся ТОЛЬКО на том, что сказано в репликах
- Защищай интересы «{role_name}»
- 1-2 предложения, конкретно

Ответь СТРОГО в формате JSON (без markdown, без ```):
{{{{
  "type": "counter",
  "text": "Подсказка...",
  "trigger": "{{keyword}}",
  "confidence": 75,
  "context_info": "краткий контекст"
}}}}"""

    STRENGTHEN_POSITION_TEMPLATE = """Ты эксперт по переговорам в строительстве. Проведи глубокий анализ позиции «{role_name}» и предложи стратегию усиления.

===== РОЛЬ И ИНТЕРЕСЫ =====
Роль: {role_name} ({role_description})
Интересы: {role_interests}
Оппоненты: {role_opponents}

===== СИТУАЦИЯ =====

{{meeting_context_block}}

===== ТИПИЧНЫЕ РИСКИ В СТРОИТЕЛЬСТВЕ =====
{risks_list}

===== ДОКУМЕНТЫ =====
{{document_context}}

===== ТРАНСКРИПЦИЯ ПЕРЕГОВОРОВ =====
{{full_transcript}}

===== ЗАДАЧА =====

Проведи структурированный анализ по разделам. Пиши кратко, каждый пункт — конкретное действие или аргумент.

**1. КАРТА ПОЗИЦИЙ**
- Позиция «{role_name}»: что уже заявлено, какие условия озвучены
- Позиция оппонента: что он хочет, на чём настаивает
- Зона возможного соглашения (ZOPA): где интересы пересекаются
{{opponent_weaknesses_analysis}}

**2. СИЛЬНЫЕ АРГУМЕНТЫ**
Перечисли 3-5 аргументов для «{role_name}», основанных на:
- Фактах из транскрипции (что оппонент сам признал или подтвердил)
- Данных из документов (конкретные суммы, пункты, условия) — если загружены
- Рыночных реалиях строительной отрасли
Каждый аргумент: формулировка + как подать (фрейминг)

**3. КОНТРАРГУМЕНТЫ НА ВОЗРАЖЕНИЯ**
Для каждого возражения оппонента (из транскрипции):
- Суть возражения (процитируй или перефразируй)
- Контраргумент с техникой: логическое опровержение / условная уступка / переформулирование / переключение фокуса
- Готовая фраза, которую можно произнести

**4. РИСКИ И ЛОВУШКИ**
- Какие из типичных рисков актуальны в этих переговорах
- Что оппонент пытается протащить (анализ скрытых целей)
- Какие пункты нужно зафиксировать письменно прямо сейчас

**5. ТАКТИЧЕСКИЙ ПЛАН НА БЛИЖАЙШИЕ 10 МИНУТ**
{{negotiation_type_strategy}}
Конкретная последовательность шагов:
- Шаг 1: ...
- Шаг 2: ...
- Шаг 3: ...
Включи: какую уступку можно предложить (и что потребовать взамен), какой якорь поставить, какой дедлайн обозначить.

**6. ТОЧКИ ДАВЛЕНИЯ**
- Где оппонент уязвим (противоречия в его словах, невыгодные для него факты из документов)
- Какие вопросы поставят его в неудобное положение
- Какие альтернативы (BATNA) можно обозначить для усиления позиции

СТРОГИЕ ПРАВИЛА:
- {role_custom_instructions}
- Основывайся ТОЛЬКО на реальном содержании транскрипции и загруженных документов
- НЕ выдумывай номера договоров, пунктов, статей — ссылайся только на то, что есть в контексте
- Если документы загружены — активно используй данные из них (суммы, условия, пункты)
- Будь кратким: каждый пункт — 1-2 предложения, без воды"""


class PromptBuilder:
    """Build prompts for LLM with role-specific data."""

    def __init__(self, role_data: dict | None = None):
        rd = role_data or DEFAULT_ROLE_DATA
        self.role_data = rd
        self.templates = PromptTemplates()

        # Pre-format role placeholders into all templates
        role_vars = {
            "role_name": rd.get("name", DEFAULT_ROLE_DATA["name"]),
            "role_description": rd.get("description", DEFAULT_ROLE_DATA["description"]),
            "role_interests": rd.get("interests", DEFAULT_ROLE_DATA["interests"]),
            "role_opponents": rd.get("opponents", DEFAULT_ROLE_DATA["opponents"]),
            "role_custom_instructions": rd.get("custom_instructions", DEFAULT_ROLE_DATA["custom_instructions"]),
        }

        # Build system prompt
        self.system_prompt = self.templates.SYSTEM_PROMPT_TEMPLATE.format(
            **role_vars, glossary=get_terms_glossary()
        )

        # Pre-bake role vars into templates (leaving {{var}} for runtime)
        self._argument = self.templates.ARGUMENT_PROMPT.format(**role_vars)
        self._strategy = self.templates.STRATEGY_PROMPT.format(**role_vars)
        self._risk = self.templates.RISK_DETECTION_PROMPT.format(**role_vars)
        self._auto_suggestion = self.templates.AUTO_SUGGESTION_PROMPT.format(**role_vars)
        self._tactical_hints = self.templates.TACTICAL_HINTS_PROMPT.format(**role_vars)
        self._auto_structured = self.templates.AUTO_SUGGESTION_STRUCTURED_PROMPT.format(**role_vars)
        self._strengthen = self.templates.STRENGTHEN_POSITION_TEMPLATE.format(
            **role_vars, risks_list=get_risks_list()
        )

        # Default suggestion type blocks (can be overridden via set_custom_suggestion_types)
        self._role_name = role_vars["role_name"]
        self._suggestion_types_block = _build_types_block(DEFAULT_SUGGESTION_TYPES)
        self._suggestion_example_block = _build_example_block(DEFAULT_SUGGESTION_TYPES)
        self._suggestion_types_block_auto = _build_types_block_auto(
            DEFAULT_SUGGESTION_TYPES, self._role_name
        )

    def set_custom_suggestion_types(self, types: list[dict] | None):
        """Override suggestion type descriptions used in prompts."""
        if not types:
            return
        enabled = [t for t in types if t.get("enabled", True)]
        if not enabled:
            return
        self._suggestion_types_block = _build_types_block(enabled)
        self._suggestion_example_block = _build_example_block(enabled)
        self._suggestion_types_block_auto = _build_types_block_auto(
            enabled, self._role_name
        )

    def _build_meeting_context_block(self, topic="", notes="",
                                      negotiation_type="", meeting_role="",
                                      opponent_weaknesses="") -> str:
        """Assemble meeting context fields into a formatted text block."""
        parts = []
        if topic:
            parts.append(f"Тема встречи: {topic}")
        if negotiation_type:
            labels = {"sale": "Продажа / заключение сделки",
                      "claim": "Претензионная работа",
                      "negotiation": "Согласование условий"}
            parts.append(f"Тип переговоров: {labels.get(negotiation_type, negotiation_type)}")
        if meeting_role:
            parts.append(f"Роль на встрече: {meeting_role}")
        if opponent_weaknesses:
            parts.append(f"Слабые стороны оппонента: {opponent_weaknesses}")
        if notes:
            parts.append(f"Ключевые условия и цели:\n{notes}")
        return "\n".join(parts) if parts else "Контекст встречи не задан."

    @staticmethod
    def _get_negotiation_type_instructions(negotiation_type: str) -> str:
        mapping = {
            "sale": (
                "СПЕЦИФИКА (продажа/сделка):\n"
                "- Фокус на ценности предложения, а не на цене\n"
                "- Используй технику «якорения» — задай рамку стоимости первым\n"
                "- Ищи момент для закрытия: когда оппонент соглашается с ценностью — фиксируй условия"
            ),
            "claim": (
                "СПЕЦИФИКА (претензия):\n"
                "- Опирайся на факты и документы, избегай эмоций\n"
                "- Фиксируй каждое признание оппонента — это уступка\n"
                "- Предлагай конкретный механизм урегулирования, не общие слова"
            ),
            "negotiation": (
                "СПЕЦИФИКА (согласование условий):\n"
                "- Используй пакетное предложение: объединяй несколько пунктов\n"
                "- Применяй принцип взаимности: каждая уступка — в обмен на встречную\n"
                "- Фиксируй согласованные пункты, чтобы не возвращаться к ним"
            ),
        }
        return mapping.get(negotiation_type, "")

    @staticmethod
    def _get_opponent_weaknesses_instruction(opponent_weaknesses: str) -> str:
        if opponent_weaknesses:
            return f"5. Учти известные слабые стороны оппонента: {opponent_weaknesses}"
        return ""

    @staticmethod
    def _get_opponent_weaknesses_analysis(opponent_weaknesses: str) -> str:
        if opponent_weaknesses:
            return (f"- Известные слабые стороны оппонента: {opponent_weaknesses}\n"
                    "- Как использовать эти слабости в аргументации (этично, но эффективно)")
        return ""

    @staticmethod
    def _get_negotiation_type_strategy(negotiation_type: str) -> str:
        mapping = {
            "sale": "Стратегия для продажи: веди к закрытию сделки, используй «если мы решим X — вы готовы Y?»",
            "claim": "Стратегия для претензии: наращивай давление фактами, фиксируй признания, предложи механизм компенсации.",
            "negotiation": "Стратегия для согласования: пакетное предложение, двигайся по пунктам, фиксируй согласованное.",
        }
        return mapping.get(negotiation_type, "Определи оптимальную тактику на основе хода переговоров.")

    def build_argument_prompt(self, context: str, topic: str,
                             recent_dialog: str,
                             document_context: str = "") -> str:
        return self._argument.format(
            context=context, topic=topic,
            recent_dialog=recent_dialog, document_context=document_context,
        )

    def build_strategy_prompt(self, context: str, recent_dialog: str) -> str:
        return self._strategy.format(
            context=context, recent_dialog=recent_dialog
        )

    def build_risk_prompt(self, recent_dialog: str) -> str:
        return self._risk.format(recent_dialog=recent_dialog)

    def build_auto_suggestion_prompt(self, keyword: str, recent_dialog: str,
                                     document_context: str = "") -> str:
        args = get_arguments_for_keyword(keyword)
        knowledge_hints = ""
        if args:
            knowledge_hints = "Рекомендации по теме:\n" + "\n".join(f"- {a}" for a in args)
        return self._auto_suggestion.format(
            keyword=keyword, knowledge_hints=knowledge_hints,
            recent_dialog=recent_dialog, document_context=document_context,
        )

    def build_auto_suggestion_structured_prompt(self, keyword: str,
                                                 recent_dialog: str,
                                                 document_context: str = "") -> str:
        args = get_arguments_for_keyword(keyword)
        knowledge_hints = ""
        if args:
            knowledge_hints = "Рекомендации по теме:\n" + "\n".join(f"- {a}" for a in args)
        return self._auto_structured.format(
            keyword=keyword, knowledge_hints=knowledge_hints,
            recent_dialog=recent_dialog, document_context=document_context,
            suggestion_types_block_auto=self._suggestion_types_block_auto,
        )

    def build_tactical_hints_prompt(self, recent_dialog: str,
                                     document_context: str = "",
                                     topic: str = "", notes: str = "",
                                     negotiation_type: str = "",
                                     meeting_role: str = "",
                                     opponent_weaknesses: str = "") -> str:
        return self._tactical_hints.format(
            meeting_context_block=self._build_meeting_context_block(
                topic, notes, negotiation_type, meeting_role, opponent_weaknesses),
            recent_dialog=recent_dialog,
            document_context=document_context,
            opponent_weaknesses_instruction=self._get_opponent_weaknesses_instruction(opponent_weaknesses),
            negotiation_type_instructions=self._get_negotiation_type_instructions(negotiation_type),
            suggestion_types_block=self._suggestion_types_block,
            suggestion_example_block=self._suggestion_example_block,
        )

    def build_strengthen_position_prompt(self, full_transcript: str,
                                         document_context: str = "",
                                         topic: str = "", notes: str = "",
                                         negotiation_type: str = "",
                                         meeting_role: str = "",
                                         opponent_weaknesses: str = "") -> str:
        return self._strengthen.format(
            full_transcript=full_transcript,
            document_context=document_context,
            meeting_context_block=self._build_meeting_context_block(
                topic, notes, negotiation_type, meeting_role, opponent_weaknesses),
            opponent_weaknesses_analysis=self._get_opponent_weaknesses_analysis(opponent_weaknesses),
            negotiation_type_strategy=self._get_negotiation_type_strategy(negotiation_type),
        )
