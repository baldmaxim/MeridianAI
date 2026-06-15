"""Схемы финализации встречи (Этап 5).

MeetingFinalizationResult — валидация JSON от LLM (устойчивая: дефолты, коэрция enum,
обрезка длинных полей). API-схемы — статус/протокол/правка.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

DECISION_STATUSES = {"accepted", "preliminary", "rejected", "postponed", "unclear"}
ACTION_STATUSES = {"open", "done", "cancelled"}
RISK_SEVERITIES = {"low", "medium", "high"}
MEETING_TYPES = {"sale", "claim", "negotiation", "internal", "technical", "legal", "other"}


def _clip(v: str | None, n: int) -> str:
    return (v or "")[:n]


class EvidenceRef(BaseModel):
    timecode: str = ""
    speaker: str = ""
    quote: str = ""

    @field_validator("timecode", "speaker", "quote", mode="before")
    @classmethod
    def _s(cls, v):
        return _clip(str(v) if v is not None else "", 400)


class SummaryPoint(BaseModel):
    text: str = ""
    evidence: list[EvidenceRef] = Field(default_factory=list)


class DecisionItem(BaseModel):
    text: str = ""
    status: str = "unclear"
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def _st(cls, v):
        v = str(v or "").lower()
        return v if v in DECISION_STATUSES else "unclear"


class ActionItemOut(BaseModel):
    task: str = ""
    owner: str = "не указано"
    due: str = "не указано"
    status: str = "open"
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def _st(cls, v):
        v = str(v or "").lower()
        return v if v in ACTION_STATUSES else "open"

    @field_validator("owner", "due", mode="before")
    @classmethod
    def _od(cls, v):
        s = str(v).strip() if v is not None else ""
        return _clip(s or "не указано", 240)


class RiskItemOut(BaseModel):
    text: str = ""
    severity: str = "medium"
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @field_validator("severity", mode="before")
    @classmethod
    def _sev(cls, v):
        v = str(v or "").lower()
        return v if v in RISK_SEVERITIES else "medium"


class OpenQuestionItem(BaseModel):
    text: str = ""
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ImportantQuote(BaseModel):
    speaker: str = ""
    timecode: str = ""
    quote: str = ""


class DocumentRef(BaseModel):
    document_name: str = ""
    reason_used: str = ""


class MeetingFinalizationResult(BaseModel):
    title: str = ""
    micro_summary: str = ""
    tags: list[str] = Field(default_factory=list)
    meeting_type: str = "other"
    protocol_markdown: str = ""
    summary_points: list[SummaryPoint] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)
    action_items: list[ActionItemOut] = Field(default_factory=list)
    risks: list[RiskItemOut] = Field(default_factory=list)
    open_questions: list[OpenQuestionItem] = Field(default_factory=list)
    important_quotes: list[ImportantQuote] = Field(default_factory=list)
    document_references: list[DocumentRef] = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v):
        return _clip(str(v or ""), 90)

    @field_validator("micro_summary", mode="before")
    @classmethod
    def _micro(cls, v):
        return _clip(str(v or ""), 220)

    @field_validator("meeting_type", mode="before")
    @classmethod
    def _mt(cls, v):
        v = str(v or "").lower()
        return v if v in MEETING_TYPES else "other"

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, v):
        if not isinstance(v, list):
            return []
        return [_clip(str(t), 40) for t in v if str(t).strip()][:12]


# --- API ---


class FinalizationStatusResponse(BaseModel):
    meeting_id: int
    status: str
    error: str | None
    finalized_at: datetime | None
    has_protocol: bool


class ProtocolDecisionOut(BaseModel):
    id: int
    text: str
    status: str
    evidence: list[dict]
    created_at: datetime


class ProtocolActionItemOut(BaseModel):
    id: int
    task: str
    owner_text: str | None
    due_text: str | None
    status: str
    evidence: list[dict]
    created_at: datetime


class ProtocolRiskOut(BaseModel):
    id: int
    text: str
    severity: str
    evidence: list[dict]
    created_at: datetime


class ProtocolOpenQuestionOut(BaseModel):
    id: int
    text: str
    evidence: list[dict]
    created_at: datetime


class MeetingProtocolResponse(BaseModel):
    meeting_id: int
    finalization_status: str
    title: str | None
    micro_summary: str | None
    tags: list[str]
    protocol_markdown: str | None
    protocol_json: dict | None
    decisions: list[ProtocolDecisionOut]
    action_items: list[ProtocolActionItemOut]
    risks: list[ProtocolRiskOut]
    open_questions: list[ProtocolOpenQuestionOut]


class ProtocolPatch(BaseModel):
    title: str | None = None
    micro_summary: str | None = None
    tags: list[str] | None = None
    protocol_markdown: str | None = None
