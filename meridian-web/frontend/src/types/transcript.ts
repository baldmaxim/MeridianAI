import type { PublicSpeakerSide } from './speaker';

export interface TranscriptionRecord {
  id: number;
  filename: string;
  format: string;
  segment_count: number | null;
  created_at: string;
}

// ElevenLabs word-level data
export interface TranscriptWord {
  text: string;
  start: number;
  end: number;
  type: string; // "word" | "spacing" | "punctuation"
  logprob: number | null;
}

// Committed segment with word-level timestamps
export interface CommittedSegmentWire {
  segment_id: string;
  segment_key: string;       // = segment_id; стабильный ключ для channel alignment (Этап 9.1)
  speaker: string;
  text: string;
  words: TranscriptWord[];
  start_time: number;
  end_time: number;
  confidence: number | null;
  timestamp: string;
  server_ts_ms: number;      // абсолютный server timeline (epoch ms)
}

// Этап 9.1: качество синхронизации часов устройства с backend.
export type ClockSyncQuality = 'excellent' | 'good' | 'fair' | 'poor';

export interface DeviceSyncState {
  offsetMs: number;
  rttMs: number;
  quality: ClockSyncQuality;
  samples: number;
  lastSyncMs: number;
}

// Этап 9.2: диагностика secondary audio shadow канала (с backend).
export type SecondaryShadowStatus = 'idle' | 'recording' | 'stale' | 'error';

export interface SecondaryShadowDiag {
  enabled: boolean;
  side_hint: PublicSpeakerSide | null;
  status: SecondaryShadowStatus;
  sample_rate: number | null;
  channels: number | null;
  codec: string | null;
  chunks_count: number;
  bytes_count: number;
  dropped_chunks: number;
  gaps_count: number;
  last_seq: number | null;
  last_duration_ms: number | null;
  last_packet_age_ms: number | null;
  estimated_buffer_ms: number;
  drift_ms: number;
  target_sample_rate: number;
  error: string | null;
}

export interface SecondaryShadowTrackSummary {
  connection_id: string;
  side_hint: PublicSpeakerSide | null;
  status: SecondaryShadowStatus;
  chunks_count: number;
  estimated_buffer_ms: number;
  sample_rate: number | null;
}

// Этап 9.3: multi-source ingest — единая server timeline всех аудиоисточников.
export type IngestRole = 'primary' | 'secondary';

export interface IngestTrackInfo {
  track_id: string;
  role: IngestRole;
  side_hint: PublicSpeakerSide | null;
  sample_rate: number;
  channels: number;
  codec: string;
  frame_ms: number;
  frame_bytes: number;
  frames_count: number;
  buffered_frames: number;
  gaps_count: number;
  duplicates_count: number;
  late_frames: number;
  jitter_ms: number;
  drift_ms: number;
  first_index: number | null;
  last_index: number | null;
}

export interface MultiSourceAlignment {
  meeting_id: number;
  frame_ms: number;
  window_ms: number;
  common_lo: number | null;
  common_hi: number | null;
  tracks: IngestTrackInfo[];
}
