"""RagHit (результат поиска письма) и формирование промпт-блока для LLM.

Чистый модуль — без IO. build_rag_context покрыт unit-тестами.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RagHit:
    """Один фрагмент письма из RAG-хранилища PayHub (поля — camelCase в JSON через to_dict)."""

    chunk_id: str
    letter_id: Optional[str]
    subject: Optional[str]
    reg_number: Optional[str]
    number: Optional[str]
    customer_number: Optional[str]
    direction: Optional[str]
    letter_date: Optional[str]
    project_id: Optional[int]
    page_from: Optional[int]
    page_to: Optional[int]
    text: str
    score: float

    def to_dict(self) -> dict:
        return {
            "chunkId": self.chunk_id,
            "letterId": self.letter_id,
            "subject": self.subject,
            "regNumber": self.reg_number,
            "number": self.number,
            "customerNumber": self.customer_number,
            "direction": self.direction,
            "letterDate": self.letter_date,
            "projectId": self.project_id,
            "pageFrom": self.page_from,
            "pageTo": self.page_to,
            "text": self.text,
            "score": self.score,
        }


def _direction_label(direction: Optional[str]) -> str:
    return "входящее" if (direction or "").strip().lower() == "incoming" else "исходящее"


def _number_label(hit: RagHit) -> str:
    return hit.reg_number or hit.number or hit.customer_number or "—"


def _pages_label(hit: RagHit) -> str:
    if hit.page_from is None and hit.page_to is None:
        return ""
    return f" · стр. {hit.page_from if hit.page_from is not None else '?'}-{hit.page_to if hit.page_to is not None else '?'}"


def build_rag_context(hits: list[RagHit]) -> str:
    """Компактный блок переписки для подмешивания в промпт LLM (или '' если пусто).

    Формат на каждый hit:
        [Письмо {i}] {входящее|исходящее} от {letter_date}
        № {reg_number||number||customer_number} · тема: {subject} · стр. {from}-{to}
        {text}
        ---
    """
    if not hits:
        return ""
    parts: list[str] = []
    for i, h in enumerate(hits, 1):
        header = (
            f"[Письмо {i}] {_direction_label(h.direction)} от {h.letter_date or '—'}\n"
            f"№ {_number_label(h)} · тема: {h.subject or '—'}{_pages_label(h)}"
        )
        parts.append(f"{header}\n{h.text or ''}\n---")
    return "\n".join(parts)
