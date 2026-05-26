"""Meeting memory — three-layer context for long meetings.

Layers:
- live_window: last N turns for immediate reaction
- rolling_summary: LLM-generated (or deterministic fallback) meeting summary
- pinned_facts: structured important facts extracted from turns
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm.client import LLMClient
    from ..transcription.turn_assembler import UtteranceTurn

logger = logging.getLogger("meridian.meeting_memory")

# ---------------------------------------------------------------------------
# Fact extraction patterns
# ---------------------------------------------------------------------------

FACT_PATTERNS: dict[str, list[str | re.Pattern]] = {
    "admission": ["согласен", "признаю", "подтверждаю", "да, это так", "вы правы"],
    "refusal": ["отказ", "не согласен", "категорически", "нет, это невозможно", "исключено"],
    "concession": ["уступ", "готов снизить", "пойдём навстречу", "в виде исключения", "можем рассмотреть"],
    "deadline": [re.compile(r"до\s+\d{1,2}[\.\-/]\d{1,2}"), "дедлайн", "крайний срок", "не позднее"],
    "amount": [re.compile(r"\d+[\s,.]?\d*\s*(руб|₽|млн|тыс|%|процент)")],
    "obligation": ["обяз", "должен", "гарантирует", "берёт на себя", "обеспечит"],
    "document_request": ["зафиксировать", "протокол", "письменно", "на бумаге", "оформить"],
}

FACT_TYPE_LABELS = {
    "admission": "Признание",
    "refusal": "Отказ",
    "concession": "Уступка",
    "deadline": "Срок",
    "amount": "Сумма",
    "obligation": "Обязательство",
    "document_request": "Фиксация",
}

SUMMARY_PROMPT = (
    "Сократи следующий диалог до 5-8 предложений. "
    "Сохрани: кто и что предложил, какие суммы/сроки озвучены, ключевые решения.\n\n"
    "{turns_text}"
)


@dataclass
class PinnedFact:
    """Single important fact extracted from a turn."""

    fact_type: str
    text: str
    speaker: str
    timestamp: datetime
    source_turn_id: str

    def format(self) -> str:
        label = FACT_TYPE_LABELS.get(self.fact_type, self.fact_type)
        ts = self.timestamp.strftime("%H:%M:%S")
        return f"[{ts}] {label} ({self.speaker}): {self.text}"


class MeetingMemory:
    """Three-layer meeting context manager."""

    def __init__(self, live_window_size: int = 10, summary_interval: int = 5):
        self._live_window_size = live_window_size
        self._summary_interval = summary_interval

        self._all_turns: List["UtteranceTurn"] = []
        self._pinned_facts: List[PinnedFact] = []
        self._seen_fact_keys: Set[str] = set()
        self._rolling_summary: str = ""
        self._turns_since_summary: int = 0
        self._summary_updating: bool = False

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_turn(self, turn: "UtteranceTurn") -> None:
        """Add a finalized turn: store it, extract facts, bump summary counter."""
        self._all_turns.append(turn)
        self._turns_since_summary += 1
        self._extract_facts(turn)

    def _extract_facts(self, turn: "UtteranceTurn") -> None:
        text_lower = turn.text.lower()
        for fact_type, patterns in FACT_PATTERNS.items():
            dedup_key = f"{turn.turn_id}:{fact_type}"
            if dedup_key in self._seen_fact_keys:
                continue
            for pat in patterns:
                matched = False
                if isinstance(pat, re.Pattern):
                    matched = bool(pat.search(text_lower))
                else:
                    matched = pat in text_lower
                if matched:
                    # Trim fact text to first ~120 chars of the turn
                    snippet = turn.text[:120].rstrip()
                    if len(turn.text) > 120:
                        snippet += "…"
                    fact = PinnedFact(
                        fact_type=fact_type,
                        text=snippet,
                        speaker=turn.speaker,
                        timestamp=turn.wall_clock,
                        source_turn_id=turn.turn_id,
                    )
                    self._pinned_facts.append(fact)
                    self._seen_fact_keys.add(dedup_key)
                    logger.info("[MeetingMemory] pinned fact: %s — %s", fact_type, snippet[:60])
                    break  # one fact per type per turn

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def needs_summary_update(self) -> bool:
        return self._turns_since_summary >= self._summary_interval and not self._summary_updating

    async def update_summary(self, llm_client: "LLMClient") -> None:
        """Update rolling summary via LLM. Safe to call as fire-and-forget task."""
        if self._summary_updating:
            return
        self._summary_updating = True
        try:
            turns_text = self._format_all_turns()
            if not turns_text:
                return
            prompt = SUMMARY_PROMPT.format(turns_text=turns_text)
            result = await llm_client.get_suggestion_async(prompt, max_tokens=300)
            if result:
                self._rolling_summary = result.strip()
                self._turns_since_summary = 0
                logger.info("[MeetingMemory] summary updated (%d chars)", len(self._rolling_summary))
        except Exception as e:
            logger.warning("[MeetingMemory] summary update failed: %s", e)
        finally:
            self._summary_updating = False

    def build_deterministic_summary(self) -> str:
        """Fallback summary without LLM: truncated first sentence per turn."""
        if not self._all_turns:
            return ""
        lines = []
        for t in self._all_turns:
            snippet = t.text[:150].rstrip()
            if len(t.text) > 150:
                snippet += "…"
            lines.append(f"{t.speaker}: {snippet}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Getters
    # ------------------------------------------------------------------

    def get_live_window(self) -> str:
        """Format last N turns."""
        recent = self._all_turns[-self._live_window_size:]
        if not recent:
            return ""
        lines = []
        for t in recent:
            ts = t.wall_clock.strftime("%H:%M:%S")
            lines.append(f"[{ts}] {t.speaker}: {t.text}")
        return "\n".join(lines)

    def get_pinned_facts_text(self) -> str:
        if not self._pinned_facts:
            return ""
        return "\n".join(f.format() for f in self._pinned_facts)

    def get_rolling_summary(self) -> str:
        return self._rolling_summary or self.build_deterministic_summary()

    # ------------------------------------------------------------------
    # Combined context for LLM prompts
    # ------------------------------------------------------------------

    def build_combined_context(self) -> str:
        """Build combined context: summary + facts + live window."""
        parts = []

        summary = self.get_rolling_summary()
        if summary:
            parts.append(f"===== СВОДКА ВСТРЕЧИ =====\n{summary}")

        facts = self.get_pinned_facts_text()
        if facts:
            parts.append(f"===== КЛЮЧЕВЫЕ ФАКТЫ =====\n{facts}")

        live = self.get_live_window()
        if live:
            parts.append(f"===== ПОСЛЕДНИЕ РЕПЛИКИ =====\n{live}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_all_turns(self) -> str:
        lines = []
        for t in self._all_turns:
            ts = t.wall_clock.strftime("%H:%M:%S")
            lines.append(f"[{ts}] {t.speaker}: {t.text}")
        return "\n".join(lines)

    @property
    def pinned_facts(self) -> List[PinnedFact]:
        return self._pinned_facts

    @property
    def turn_count(self) -> int:
        return len(self._all_turns)

    def reset(self) -> None:
        self._all_turns.clear()
        self._pinned_facts.clear()
        self._seen_fact_keys.clear()
        self._rolling_summary = ""
        self._turns_since_summary = 0
        self._summary_updating = False
