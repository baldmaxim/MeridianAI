"""Схемы AI-настроек (Этап 9): профили, resolved-настройки, options, patch встречи."""

from datetime import datetime
from typing import Any

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
    # Скрытый per-meeting/canary override Signal Engine (НЕ профильная настройка, не для UI).
    # None = использовать глобальный config. См. docs/signal_engine_canary.md.
    signal_engine_enabled: bool | None = None
    signal_engine_shadow_mode: bool | None = None
    signal_engine_allow_legacy_fallback: bool | None = None
    signal_engine_min_confidence: float | None = None
    signal_engine_min_actionability: float | None = None
    signal_engine_min_urgency: float | None = None
    signal_engine_trace_enabled: bool | None = None
    signal_engine_trace_include_text: bool | None = None
    signal_engine_trace_sample_rate: float | None = None
    signal_engine_llm_timeout_seconds: float | None = None
    # Скрытый per-meeting маппинг speaker labels/sources/channels → сторона (Этап 5).
    speaker_identity_hints: dict[str, Any] | None = None
    # Скрытый per-meeting canary override Source Reconciliation (Этап 11).
    source_reconcile_enabled: bool | None = None
    source_reconcile_shadow_mode: bool | None = None
    source_reconcile_min_candidate_confidence: float | None = None
    source_reconcile_min_time_overlap: float | None = None
    source_reconcile_min_text_similarity: float | None = None
    source_reconcile_min_match_score: float | None = None
    source_reconcile_ambiguity_margin: float | None = None
    source_reconcile_max_candidates: int | None = None
    source_reconcile_max_age_ms: int | None = None
    source_reconcile_trace_enabled: bool | None = None
    source_reconcile_trace_sample_rate: float | None = None
    # Скрытый per-meeting canary override Per-channel STT (Этап 17). None = global config.
    audio_per_channel_stt_enabled: bool | None = None
    audio_per_channel_stt_shadow_mode: bool | None = None
    audio_per_channel_stt_trace_enabled: bool | None = None
    audio_per_channel_stt_trace_sample_rate: float | None = None
    audio_per_channel_stt_max_channels: int | None = None
    audio_per_channel_stt_min_rms: float | None = None
    audio_per_channel_stt_min_dominance: float | None = None
    audio_per_channel_stt_min_segment_ms: int | None = None
    audio_per_channel_stt_end_silence_ms: int | None = None
    audio_per_channel_stt_max_segment_ms: int | None = None
    audio_per_channel_stt_min_text_chars: int | None = None
    audio_per_channel_stt_max_segments_per_minute: int | None = None
    audio_per_channel_stt_max_concurrent_transcribes: int | None = None
    # Provider adapter (Этап 18). None = global config. API-ключи здесь НЕ хранятся.
    audio_per_channel_stt_provider: str | None = None
    audio_per_channel_stt_timeout_seconds: float | None = None
    audio_per_channel_stt_language_code: str | None = None
    audio_per_channel_stt_model_id: str | None = None
    audio_per_channel_stt_cache_enabled: bool | None = None
    audio_per_channel_stt_cache_max_entries: int | None = None
    audio_per_channel_stt_max_audio_seconds: float | None = None
    audio_per_channel_stt_max_wav_bytes: int | None = None
    audio_per_channel_stt_max_provider_calls_per_meeting: int | None = None
    audio_per_channel_stt_max_provider_audio_seconds_per_meeting: float | None = None


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
    # Скрытый per-meeting/canary override Signal Engine (НЕ профильная настройка, не для UI).
    # None = очистить override / использовать глобальный config. См. docs/signal_engine_canary.md.
    signal_engine_enabled: bool | None = None
    signal_engine_shadow_mode: bool | None = None
    signal_engine_allow_legacy_fallback: bool | None = None
    signal_engine_min_confidence: float | None = None
    signal_engine_min_actionability: float | None = None
    signal_engine_min_urgency: float | None = None
    signal_engine_trace_enabled: bool | None = None
    signal_engine_trace_include_text: bool | None = None
    signal_engine_trace_sample_rate: float | None = None
    signal_engine_llm_timeout_seconds: float | None = None
    # Скрытый per-meeting маппинг speaker labels/sources/channels → сторона (Этап 5).
    speaker_identity_hints: dict[str, Any] | None = None
    # Скрытый per-meeting canary override Source Reconciliation (Этап 11).
    source_reconcile_enabled: bool | None = None
    source_reconcile_shadow_mode: bool | None = None
    source_reconcile_min_candidate_confidence: float | None = None
    source_reconcile_min_time_overlap: float | None = None
    source_reconcile_min_text_similarity: float | None = None
    source_reconcile_min_match_score: float | None = None
    source_reconcile_ambiguity_margin: float | None = None
    source_reconcile_max_candidates: int | None = None
    source_reconcile_max_age_ms: int | None = None
    source_reconcile_trace_enabled: bool | None = None
    source_reconcile_trace_sample_rate: float | None = None
    # Скрытый per-meeting canary override Per-channel STT (Этап 17). None = global config.
    audio_per_channel_stt_enabled: bool | None = None
    audio_per_channel_stt_shadow_mode: bool | None = None
    audio_per_channel_stt_trace_enabled: bool | None = None
    audio_per_channel_stt_trace_sample_rate: float | None = None
    audio_per_channel_stt_max_channels: int | None = None
    audio_per_channel_stt_min_rms: float | None = None
    audio_per_channel_stt_min_dominance: float | None = None
    audio_per_channel_stt_min_segment_ms: int | None = None
    audio_per_channel_stt_end_silence_ms: int | None = None
    audio_per_channel_stt_max_segment_ms: int | None = None
    audio_per_channel_stt_min_text_chars: int | None = None
    audio_per_channel_stt_max_segments_per_minute: int | None = None
    audio_per_channel_stt_max_concurrent_transcribes: int | None = None
    # Provider adapter (Этап 18). None = global config. API-ключи здесь НЕ хранятся.
    audio_per_channel_stt_provider: str | None = None
    audio_per_channel_stt_timeout_seconds: float | None = None
    audio_per_channel_stt_language_code: str | None = None
    audio_per_channel_stt_model_id: str | None = None
    audio_per_channel_stt_cache_enabled: bool | None = None
    audio_per_channel_stt_cache_max_entries: int | None = None
    audio_per_channel_stt_max_audio_seconds: float | None = None
    audio_per_channel_stt_max_wav_bytes: int | None = None
    audio_per_channel_stt_max_provider_calls_per_meeting: int | None = None
    audio_per_channel_stt_max_provider_audio_seconds_per_meeting: float | None = None
