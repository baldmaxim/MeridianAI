"""Settings schemas."""

import json

from pydantic import BaseModel, field_validator


class SuggestionTypeConfig(BaseModel):
    key: str
    badge: str
    color: str
    metaLabel: str | None = None
    actionLabel: str = "Использовать"
    secondaryAction: str | None = None
    llm_description: str
    enabled: bool = True


class TriggerKeywordConfig(BaseModel):
    keyword: str
    status_message: str
    enabled: bool = True


class UserSettingsResponse(BaseModel):
    stt_provider: str
    llm_model: str
    temperature: float
    user_role: str
    use_streaming: bool
    diarization: bool
    diarization_max_speakers: int
    silence_filter: bool
    custom_suggestion_types: list[SuggestionTypeConfig] | None = None
    custom_trigger_keywords: list[TriggerKeywordConfig] | None = None
    local_storage_path: str | None = None

    model_config = {"from_attributes": True}

    @field_validator("custom_suggestion_types", "custom_trigger_keywords", mode="before")
    @classmethod
    def parse_json_str(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


class UserSettingsUpdate(BaseModel):
    stt_provider: str | None = None
    llm_model: str | None = None
    temperature: float | None = None
    user_role: str | None = None
    use_streaming: bool | None = None
    diarization: bool | None = None
    diarization_max_speakers: int | None = None
    silence_filter: bool | None = None

    @field_validator("diarization_max_speakers")
    @classmethod
    def clamp_max_speakers(cls, v):
        if v is None:
            return v
        return max(2, min(6, int(v)))
    custom_suggestion_types: list[SuggestionTypeConfig] | None = None
    custom_trigger_keywords: list[TriggerKeywordConfig] | None = None
    local_storage_path: str | None = None


class ApiKeyCreate(BaseModel):
    service: str  # elevenlabs, deepgram, speechmatics, openrouter, lm_studio
    api_key: str


class ApiKeyResponse(BaseModel):
    id: int
    service: str
    key_masked: str
    is_active: bool

    model_config = {"from_attributes": True}


class ApiKeyUpdate(BaseModel):
    api_key: str | None = None
    is_active: bool | None = None
