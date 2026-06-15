"""Структурированные live-подсказки (Этап 6).

SuggestionCard — единая карточка с типом, готовой фразой, объяснением и evidence.
Валидация устойчива: коэрция enum, нормализация confidence в 0..1, дефолты.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

SUGGESTION_TYPES = {
    "say_now", "ask", "counter", "risk", "fixation",
    "trade_concession", "pause", "clarify", "summarize",
}
EVIDENCE_SOURCES = {
    "transcript", "document", "meeting_context",
    "previous_meeting", "playbook", "protocol", "unknown",
}
SOURCE_MODES = {"auto", "manual", "strengthen", "fallback"}


def _norm_conf(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    if f > 1.0:
        # near-1 float (1..2) — обрезаем до 1.0; иначе считаем процентами (0..100)
        f = 1.0 if f <= 2.0 else f / 100.0
    return max(0.0, min(1.0, f))


class SuggestionEvidence(BaseModel):
    source: str = "unknown"
    ref: str | None = None
    text: str = ""
    confidence: float | None = None

    @field_validator("source", mode="before")
    @classmethod
    def _src(cls, v):
        v = str(v or "").lower()
        return v if v in EVIDENCE_SOURCES else "unknown"

    @field_validator("text", mode="before")
    @classmethod
    def _txt(cls, v):
        return str(v or "")[:220]

    @field_validator("ref", mode="before")
    @classmethod
    def _ref(cls, v):
        return (str(v)[:240]) if v is not None else None

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        return _norm_conf(v)


class SuggestionCard(BaseModel):
    id: str | None = None
    type: str = "clarify"
    priority: int = 3
    title: str = ""
    text: str = ""
    why: str = ""
    evidence: list[SuggestionEvidence] = Field(default_factory=list)
    confidence: float = 0.5
    needs_user_check: bool = False
    created_at: datetime | None = None
    trigger: str | None = None
    source_mode: str = "auto"

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v):
        v = str(v or "").lower()
        return v if v in SUGGESTION_TYPES else "clarify"

    @field_validator("source_mode", mode="before")
    @classmethod
    def _sm(cls, v):
        v = str(v or "").lower()
        return v if v in SOURCE_MODES else "auto"

    @field_validator("priority", mode="before")
    @classmethod
    def _prio(cls, v):
        try:
            return max(1, min(9, int(v)))
        except (ValueError, TypeError):
            return 3

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v):
        return str(v or "")[:120]

    @field_validator("text", mode="before")
    @classmethod
    def _text(cls, v):
        return str(v or "")[:280]

    @field_validator("why", mode="before")
    @classmethod
    def _why(cls, v):
        return str(v or "")[:180]

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        c = _norm_conf(v)
        return 0.5 if c is None else c


class SuggestionResponse(BaseModel):
    cards: list[SuggestionCard] = Field(default_factory=list)
    raw_text: str | None = None
    model: str | None = None
    degraded: bool = False
