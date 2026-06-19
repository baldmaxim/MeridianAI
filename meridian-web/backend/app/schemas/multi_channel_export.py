"""Схемы multi-channel WAV export (Этап 9.4)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _reject_bool_int(v):
    # bool — подкласс int; не принимаем true/false вместо числа
    if isinstance(v, bool):
        raise ValueError("must be an integer, not a boolean")
    return v


class MultiChannelExportRequest(BaseModel):
    track_ids: list[str] | None = None
    window_mode: Literal["common", "last", "explicit"] = "last"
    duration_seconds: int | None = None
    # server-таймстемпы — неотрицательный epoch-ms с разумным потолком (year ~2100):
    # отсекает абсурдные значения до бэкенда (defense-in-depth к лимиту окна).
    start_server_ms: int | None = Field(default=None, ge=0, le=4_102_444_800_000)
    end_server_ms: int | None = Field(default=None, ge=0, le=4_102_444_800_000)
    channel_offsets_ms: dict[str, int] = Field(default_factory=dict)
    include_stopped: bool = False

    @field_validator("duration_seconds", "start_server_ms", "end_server_ms", mode="before")
    @classmethod
    def _no_bool(cls, v):
        return v if v is None else _reject_bool_int(v)

    @field_validator("track_ids")
    @classmethod
    def _validate_track_ids(cls, v):
        if v is None:
            return v
        if any(not isinstance(t, str) or not t.strip() for t in v):
            raise ValueError("track_ids must be non-empty strings")
        if len(set(v)) != len(v):
            raise ValueError("track_ids must be unique")
        return v

    @field_validator("channel_offsets_ms", mode="before")
    @classmethod
    def _validate_offsets(cls, v):
        if not isinstance(v, dict):
            raise ValueError("channel_offsets_ms must be an object")
        for k, val in v.items():
            _reject_bool_int(val)
            if not isinstance(val, int):
                raise ValueError("offset values must be integers")
        return v

    @field_validator("duration_seconds")
    @classmethod
    def _positive_duration(cls, v):
        if v is not None and v <= 0:
            raise ValueError("duration_seconds must be positive")
        return v

    @model_validator(mode="after")
    def _validate_window(self):
        if self.window_mode == "explicit":
            if self.start_server_ms is None or self.end_server_ms is None:
                raise ValueError("explicit window requires start_server_ms and end_server_ms")
            if self.end_server_ms <= self.start_server_ms:
                raise ValueError("end_server_ms must be greater than start_server_ms")
        return self


class MultiChannelExportChannelOut(BaseModel):
    channel_index: int
    track_id: str
    label: str
    source_kind: str
    side_hint: str | None = None
    generation: int
    offset_ms: int
    available_frames: int
    missing_frames: int
    gap_ratio: float
    clock_quality: str | None = None
    jitter_ms_p95: float | None = None
    drift_ppm: float | None = None


class MultiChannelExportPlanOut(BaseModel):
    meeting_id: int
    created_at: str | None = None
    format: str
    sample_rate: int
    bits_per_sample: int
    channels_count: int
    duration_ms: int
    start_server_ms: int
    end_server_ms: int
    frame_ms: int
    data_bytes: int
    wav_bytes: int
    channels: list[MultiChannelExportChannelOut]
    warnings: list[str]
