"""Схемы batch multi-channel STT (Этап 9.5)."""

from pydantic import BaseModel, Field, model_validator

from .multi_channel_export import MultiChannelExportRequest


class MultiChannelBatchSttRequest(BaseModel):
    export: MultiChannelExportRequest
    channel_side_overrides: dict[str, str | None] = Field(default_factory=dict)
    compare_with_live: bool = True

    @model_validator(mode="after")
    def _validate(self):
        tids = self.export.track_ids
        # batch требует явный выбор >= 2 каналов (export-схема уже проверила unique/non-empty)
        if not tids or len(tids) < 2:
            raise ValueError("batch STT requires at least 2 selected tracks")
        selected = set(tids)
        bad = [k for k in self.channel_side_overrides if k not in selected]
        if bad:
            raise ValueError(f"channel_side_overrides reference unselected tracks: {bad}")
        return self


# --- typed outputs (для документации; сериализация в API через явные dict-билдеры) ---

class MultiChannelBatchWordOut(BaseModel):
    text: str
    start: float
    end: float
    channel_index: int
    confidence: float | None = None
    punctuated_word: str | None = None


class MultiChannelBatchSegmentOut(BaseModel):
    segment_id: str
    channel_index: int
    track_id: str
    channel_label: str
    side: str | None = None
    text: str
    start: float
    end: float
    confidence: float | None = None
    words: list[MultiChannelBatchWordOut] = Field(default_factory=list)


class MultiChannelBatchChannelOut(BaseModel):
    channel_index: int
    track_id: str
    channel_label: str
    side: str | None = None
    source_kind: str
    generation: int
    transcript: str
    words_count: int
    segments_count: int
    average_confidence: float | None = None
    segments: list[MultiChannelBatchSegmentOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MultiChannelBatchResultOut(BaseModel):
    provider: str
    model: str
    language: str
    provider_request_id: str | None = None
    sample_rate: int
    channels_count: int
    duration_ms: int
    channels: list[MultiChannelBatchChannelOut] = Field(default_factory=list)
    chronological_segments: list[MultiChannelBatchSegmentOut] = Field(default_factory=list)
    combined_text: str
    warnings: list[str] = Field(default_factory=list)
    provider_meta: dict = Field(default_factory=dict)


class MultiChannelBatchJobOut(BaseModel):
    job_id: str
    meeting_id: int
    status: str
    stage: str
    progress: float
    provider: str
    model: str
    language: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    expires_at: str | None = None
    result: MultiChannelBatchResultOut | None = None
    comparison: dict | None = None
    export_manifest: dict | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
