"""Rule-based negotiation event detector.

Scans turn/segment text for high-level negotiation situations
(price pressure, stalling, liability shift, etc.) that are more
actionable than raw keyword matches.

Designed to be extended with an LLM classifier later — the
`detect()` interface stays the same.
"""

import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger("meridian.event_detector")


@dataclass(frozen=True)
class DetectedEvent:
    """A negotiation event detected in text."""

    event_type: str          # e.g. "price_pressure"
    trigger_phrase: str      # the pattern that matched
    status_message: str      # shown in analysis_status UI
    keyword_for_prompt: str  # passed to build_auto_suggestion_structured_prompt


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

_EVENT_RULES: List[dict] = [
    {
        "event_type": "price_pressure",
        "patterns": [
            "дорого", "снизить цену", "неконкурентн", "бюджет не позвол",
            "завышен", "слишком высок", "не устраивает цена",
        ],
        "status_message": "Обнаружено давление по цене…",
        "keyword_for_prompt": "давление по цене",
    },
    {
        "event_type": "deadline_pressure",
        "patterns": [
            "не успе", "перенести срок", "задержк", "опозда",
            "сорвём сроки", "сроки горят", "не укладыва",
        ],
        "status_message": "Давление по срокам…",
        "keyword_for_prompt": "давление по срокам",
    },
    {
        "event_type": "liability_shift",
        "patterns": [
            "это ваша зона", "вы должны были", "не наша ответственность",
            "ваша обязанность", "вы обещали", "это ваша проблема",
        ],
        "status_message": "Попытка переноса ответственности…",
        "keyword_for_prompt": "перенос ответственности",
    },
    {
        "event_type": "concession_request",
        "patterns": [
            "скидк", "уступ", "пойти навстречу", "снизить стоимость",
            "дисконт", "льготн", "особые условия",
        ],
        "status_message": "Запрос уступки…",
        "keyword_for_prompt": "запрос уступки",
    },
    {
        "event_type": "fixation_request",
        "patterns": [
            "зафиксировать", "в протокол", "письменно",
            "оформить", "подписать", "на бумаге",
        ],
        "status_message": "Запрос фиксации…",
        "keyword_for_prompt": "запрос фиксации договорённостей",
    },
    {
        "event_type": "contradiction_signal",
        "patterns": [
            "но вы же говорили", "ранее вы сказали", "противоречит",
            "не совпадает", "вы утверждали", "раньше было иначе",
        ],
        "status_message": "Противоречие в позиции…",
        "keyword_for_prompt": "противоречие в позиции оппонента",
    },
    {
        "event_type": "stalling",
        "patterns": [
            "подумаем", "вернёмся к этому", "не готов ответить",
            "нужно согласовать", "позже обсудим", "возьму паузу",
            "надо посоветоваться",
        ],
        "status_message": "Затягивание решения…",
        "keyword_for_prompt": "затягивание и уклонение от решения",
    },
]


class EventDetector:
    """Detect negotiation events via rule-based pattern matching.

    Each rule has a list of sub-string patterns checked against
    lowercased text.  Returns at most one DetectedEvent per event_type.
    """

    def __init__(self, rules: List[dict] | None = None):
        self._rules = rules or _EVENT_RULES

    def detect(self, text: str) -> List[DetectedEvent]:
        """Scan *text* and return all matching events (one per type max)."""
        text_lower = text.lower()
        results: List[DetectedEvent] = []

        for rule in self._rules:
            for pattern in rule["patterns"]:
                if pattern in text_lower:
                    ev = DetectedEvent(
                        event_type=rule["event_type"],
                        trigger_phrase=pattern,
                        status_message=rule["status_message"],
                        keyword_for_prompt=rule["keyword_for_prompt"],
                    )
                    results.append(ev)
                    logger.info("[EventDetector] %s (matched '%s')",
                                ev.event_type, pattern)
                    break  # one match per rule is enough

        return results
