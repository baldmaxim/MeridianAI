import type { PublicSpeakerSide } from './speaker';

// Этап 9.6: realtime multi-channel live STT shadow (диагностический candidate).
export type MultiChannelLiveStatus =
  | 'idle' | 'buffering' | 'connecting' | 'streaming'
  | 'degraded' | 'stopping' | 'stopped' | 'failed';

export interface MultiChannelLiveChannel {
  channel_index: number;
  track_id: string;
  connection_id: string;
  generation: number;
  source_kind: string;
  label: string;
  side: PublicSpeakerSide | null;
}

export interface MultiChannelLiveWord {
  text: string;
  start: number;
  end: number;
  confidence: number | null;
  punctuated_word: string | null;
}

export interface MultiChannelLiveSegment {
  segment_id: string;
  session_id: string;
  channel_index: number;
  channels_count: number;
  track_id: string;
  channel_label: string;
  side: PublicSpeakerSide | null;
  transcript: string;
  confidence: number | null;
  provider_start: number;
  provider_end: number;
  start_server_ms: number;
  end_server_ms: number;
  is_final: boolean;
  speech_final: boolean;
  words: MultiChannelLiveWord[];
}

export interface MultiChannelLiveState {
  session_id: string | null;
  status: MultiChannelLiveStatus;
  provider?: string;
  model?: string;
  language?: string;
  channel_count: number;
  channels: MultiChannelLiveChannel[];
  started_at?: string | null;
  start_frame_index?: number | null;
  start_server_ms?: number | null;
  chunks_sent?: number;
  frames_sent?: number;
  bytes_sent?: number;
  provider_queue_depth?: number;
  provider_request_id?: string | null;
  silence_ratio_by_channel?: number[];
  error_code?: string | null;
  error_message?: string | null;
}

export interface MultiChannelLiveSnapshot {
  state: MultiChannelLiveState;
  final_segments: MultiChannelLiveSegment[];
  latest_interim_by_channel: Record<string, MultiChannelLiveSegment>;
}

// Этап 9.7: channel-aware reconciliation (evidence-слой; применение только вручную).
export type ReconciliationEntryKind = 'matched' | 'ambiguous' | 'channel_only' | 'primary_only';
export type ReconciliationSideAgreement = 'suggested' | 'confirmed' | 'conflict' | 'unknown';

export interface MultiChannelReconciliationAlternative {
  channel_segment_id: string;
  channel_index: number;
  match_score: number;
  temporal_score: number;
  text_score: number;
}

export interface MultiChannelReconciliationEntry {
  entry_id: string;
  kind: ReconciliationEntryKind;
  primary_segment_key: string | null;
  channel_segment_id: string | null;
  primary_text: string | null;
  channel_text: string | null;
  primary_start_server_ms: number | null;
  primary_end_server_ms: number | null;
  channel_start_server_ms: number | null;
  channel_end_server_ms: number | null;
  original_speaker_label: string | null;
  effective_speaker_label: string | null;
  current_side: PublicSpeakerSide | null;
  has_segment_correction: boolean;
  channel_index: number | null;
  track_id: string | null;
  source_connection_id: string | null;
  source_kind: string | null;
  generation: number | null;
  channel_label: string | null;
  channel_side: PublicSpeakerSide | null;
  provider_confidence: number | null;
  temporal_score: number;
  text_score: number;
  match_score: number;
  hint_confidence: number;
  side_agreement: ReconciliationSideAgreement;
  can_apply_side: boolean;
  requires_conflict_confirmation: boolean;
  alternatives: MultiChannelReconciliationAlternative[];
  warnings: string[];
}

export interface MultiChannelReconciliationSummary {
  primary_segments: number;
  channel_segments: number;
  matched: number;
  ambiguous: number;
  channel_only: number;
  primary_only: number;
  suggested: number;
  confirmed: number;
  conflicts: number;
  unknown_side: number;
  applicable: number;
}

export interface MultiChannelReconciliationState {
  session_id: string;
  meeting_id: number;
  revision: number;
  generated_at: string;
  truncated: boolean;
  summary: MultiChannelReconciliationSummary;
  entries: MultiChannelReconciliationEntry[];
  warnings: string[];
}
