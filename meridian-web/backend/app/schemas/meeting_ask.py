"""Схемы «Спросить по встрече»."""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

AskSourceKind = Literal["document", "meeting", "transcript", "note", "knowledge"]


class MeetingAskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class MeetingAskSource(BaseModel):
    kind: AskSourceKind
    title: str
    ref: str | None = None


class MeetingAskResponse(BaseModel):
    answer: str
    sources: list[MeetingAskSource]
