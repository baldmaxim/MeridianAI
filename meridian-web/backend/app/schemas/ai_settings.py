"""Схемы AI-настроек (Этап 9): профили, resolved-настройки, options, patch встречи."""

from datetime import datetime

from pydantic import BaseModel, Field


class AISettingsProfileOut(BaseModel):
    id: int
    owner_user_id: int
    name: str
    description: str | None
    is_default: bool
    profile_type: str
    stt_provider: str | None
    stt_model: str | None
    llm_provider: str | None
    live_suggestion_model: str | None
    strengthen_model: str | None
    finalization_model: str | None
    learning_model: str | None
    suggestion_mode: str
    auto_suggestions_enabled: bool
    document_context_enabled: bool
    knowledge_context_enabled: bool
    previous_meetings_context_enabled: bool
    suggestion_structured_enabled: bool
    finalization_enabled: bool
    learning_extraction_enabled: bool
    conversation_tree_enabled: bool
    max_auto_cards: int
    max_manual_cards: int
    auto_suggestion_min_interval_seconds: int
    document_context_max_chunks: int | None
    document_context_max_chars: int | None
    previous_context_max_meetings: int | None
    previous_context_max_chars: int | None
    knowledge_context_max_items: int | None
    settings_json: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AISettingsProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    suggestion_mode: str = "balanced"
    stt_provider: str | None = None
    stt_model: str | None = None
    llm_provider: str | None = None
    live_suggestion_model: str | None = None
    strengthen_model: str | None = None
    finalization_model: str | None = None
    learning_model: str | None = None
    auto_suggestions_enabled: bool | None = None
    document_context_enabled: bool | None = None
    knowledge_context_enabled: bool | None = None
    previous_meetings_context_enabled: bool | None = None
    suggestion_structured_enabled: bool | None = None
    finalization_enabled: bool | None = None
    learning_extraction_enabled: bool | None = None
    conversation_tree_enabled: bool | None = None
    max_auto_cards: int | None = None
    max_manual_cards: int | None = None
    auto_suggestion_min_interval_seconds: int | None = None
    document_context_max_chunks: int | None = None
    document_context_max_chars: int | None = None
    previous_context_max_meetings: int | None = None
    previous_context_max_chars: int | None = None
    knowledge_context_max_items: int | None = None


class AISettingsProfileUpdate(AISettingsProfileCreate):
    name: str | None = Field(default=None, max_length=150)


class AISettingsResolved(BaseModel):
    stt_provider: str | None = None
    stt_model: str | None = None
    llm_provider: str | None = None
    live_suggestion_model: str | None = None
    strengthen_model: str | None = None
    finalization_model: str | None = None
    learning_model: str | None = None
    mode: str = "balanced"
    auto_suggestions_enabled: bool = True
    suggestion_structured_enabled: bool = True
    document_context_enabled: bool = True
    knowledge_context_enabled: bool = True
    previous_meetings_context_enabled: bool = True
    finalization_enabled: bool = True
    learning_extraction_enabled: bool = True
    conversation_tree_enabled: bool = True
    max_auto_cards: int = 2
    max_manual_cards: int = 5
    auto_suggestion_min_interval_seconds: int = 20
    document_context_max_chunks: int | None = None
    document_context_max_chars: int | None = None
    previous_context_max_meetings: int | None = None
    previous_context_max_chars: int | None = None
    knowledge_context_max_items: int | None = None
    profile_id: int | None = None


class MeetingAISettingsOut(BaseModel):
    meeting_id: int
    profile_id: int | None
    resolved: AISettingsResolved
    has_snapshot: bool
    can_edit: bool


class MeetingAISettingsPatch(BaseModel):
    mode: str | None = None
    stt_provider: str | None = None
    stt_model: str | None = None
    llm_provider: str | None = None
    live_suggestion_model: str | None = None
    strengthen_model: str | None = None
    finalization_model: str | None = None
    learning_model: str | None = None
    auto_suggestions_enabled: bool | None = None
    suggestion_structured_enabled: bool | None = None
    document_context_enabled: bool | None = None
    knowledge_context_enabled: bool | None = None
    previous_meetings_context_enabled: bool | None = None
    finalization_enabled: bool | None = None
    learning_extraction_enabled: bool | None = None
    conversation_tree_enabled: bool | None = None
    max_auto_cards: int | None = None
    max_manual_cards: int | None = None
    auto_suggestion_min_interval_seconds: int | None = None
    document_context_max_chunks: int | None = None
    document_context_max_chars: int | None = None
    previous_context_max_meetings: int | None = None
    previous_context_max_chars: int | None = None
    knowledge_context_max_items: int | None = None
