import api from './client';

// Этап 9.4: API диагностического многоканального WAV-экспорта.

export type MultiChannelWindowMode = 'common' | 'last' | 'explicit';

export interface MultiChannelExportRequest {
  track_ids?: string[];
  window_mode: MultiChannelWindowMode;
  duration_seconds?: number;
  start_server_ms?: number;
  end_server_ms?: number;
  channel_offsets_ms?: Record<string, number>;
  include_stopped?: boolean;
}

export interface MultiChannelExportChannel {
  channel_index: number;
  track_id: string;
  label: string;
  source_kind: string;
  side_hint: string | null;
  generation: number;
  offset_ms: number;
  available_frames: number;
  missing_frames: number;
  gap_ratio: number;
  clock_quality: string | null;
  jitter_ms_p95: number | null;
  drift_ppm: number | null;
}

export interface MultiChannelExportPlan {
  meeting_id: number;
  created_at?: string | null;
  format: string;
  sample_rate: number;
  bits_per_sample: number;
  channels_count: number;
  duration_ms: number;
  start_server_ms: number;
  end_server_ms: number;
  frame_ms: number;
  data_bytes: number;
  wav_bytes: number;
  channels: MultiChannelExportChannel[];
  warnings: string[];
}

export async function getMultiChannelExportPlan(
  meetingId: number,
  body: MultiChannelExportRequest,
): Promise<MultiChannelExportPlan> {
  const { data } = await api.post<MultiChannelExportPlan>(
    `/meetings/${meetingId}/multi-source/export-plan`, body,
  );
  return data;
}

export async function downloadMultiChannelWav(
  meetingId: number,
  body: MultiChannelExportRequest,
): Promise<Blob> {
  const { data } = await api.post<Blob>(
    `/meetings/${meetingId}/multi-source/wav`, body, { responseType: 'blob' },
  );
  return data;
}
