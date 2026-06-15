"""Схемы controlled auto-learning (Этап 7): извлечение кандидатов + API знаний."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

CANDIDATE_TYPES = {"term", "trigger_phrase", "playbook", "counterparty_trait", "forbidden_phrase"}
EVENT_TYPES = {"price_pressure", "deadline_pressure", "liability_shift", "concession_request",
               "fixation_request", "stalling", "contradiction_signal", "other"}
TECHNIQUES = {"conditional_concession", "calibrated_question", "fixation", "reframing",
              "risk_transfer_block", "other"}
SCOPES = {"global", "customer", "object"}
SOURCE_REF_TYPES = {"transcript", "protocol", "document", "decision", "risk", "action_item"}


def _conf(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    if f > 1.0:
        f = 1.0 if f <= 2.0 else f / 100.0
    return max(0.0, min(1.0, f))


# --- LLM extraction ---

class SourceRef(BaseModel):
    type: str = "transcript"
    ref: str | None = None
    text: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def _t(cls, v):
        v = str(v or "").lower()
        return v if v in SOURCE_REF_TYPES else "transcript"

    @field_validator("text", mode="before")
    @classmethod
    def _txt(cls, v):
        return str(v or "")[:300]


class LearningCandidateOut(BaseModel):
    candidate_type: str
    title: str = ""
    confidence: float | None = None
    source_text: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)

    @field_validator("candidate_type", mode="before")
    @classmethod
    def _ct(cls, v):
        return str(v or "").lower()

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v):
        return str(v or "")[:300]

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v):
        return _conf(v)


class LearningExtractionResult(BaseModel):
    candidates: list[LearningCandidateOut] = Field(default_factory=list)


# --- API: candidates ---

class LearningCandidateResponse(BaseModel):
    id: int
    owner_user_id: int
    customer_id: int | None
    object_id: int | None
    meeting_id: int | None
    candidate_type: str
    title: str
    payload: dict
    source_text: str | None
    source_refs: list[dict]
    confidence: float | None
    status: str
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LearningCandidatePatch(BaseModel):
    title: str | None = None
    payload: dict | None = None
    source_text: str | None = None
    confidence: float | None = None


# --- API: knowledge items (from ORM) ---

class GlossaryTermOut(BaseModel):
    id: int
    customer_id: int | None
    object_id: int | None
    term: str
    definition: str
    aliases_json: str | None
    scope: str
    status: str
    use_count: int
    created_from_meeting_id: int | None
    created_at: datetime
    model_config = {"from_attributes": True}


class TriggerPhraseOut(BaseModel):
    id: int
    customer_id: int | None
    object_id: int | None
    phrase: str
    event_type: str
    recommended_reaction: str
    scope: str
    status: str
    use_count: int
    created_from_meeting_id: int | None
    created_at: datetime
    model_config = {"from_attributes": True}


class NegotiationPlaybookOut(BaseModel):
    id: int
    customer_id: int | None
    object_id: int | None
    situation: str
    recommended_phrase: str
    technique: str
    ask_in_return_json: str | None
    risks_json: str | None
    scope: str
    status: str
    use_count: int
    created_from_meeting_id: int | None
    created_at: datetime
    model_config = {"from_attributes": True}


class CounterpartyTraitOut(BaseModel):
    id: int
    customer_id: int | None
    object_id: int | None
    trait: str
    evidence: str | None
    recommended_strategy: str | None
    scope: str
    status: str
    confidence: float | None
    created_from_meeting_id: int | None
    created_at: datetime
    model_config = {"from_attributes": True}


class ForbiddenPhraseOut(BaseModel):
    id: int
    customer_id: int | None
    object_id: int | None
    phrase_or_risk: str
    better_alternative: str | None
    reason: str | None
    scope: str
    status: str
    created_from_meeting_id: int | None
    created_at: datetime
    model_config = {"from_attributes": True}
