import api from './client';
import type { PublicSpeakerSide } from '../types';
import type { MultiChannelExportRequest } from './multiChannelExport';

// Этап 9.5: batch multi-channel STT (диагностический кандидат, live transcript не меняется).

export type MultiChannelBatchJobStatus =
  | 'queued' | 'preparing' | 'transcribing' | 'parsing' | 'comparing'
  | 'succeeded' | 'failed' | 'cancelled' | 'expired';

export interface MultiChannelBatchWord {
  text: string;
  start: number;
  end: number;
  channel_index: number;
  confidence: number | null;
  punctuated_word: string | null;
}

export interface MultiChannelBatchSegment {
  segment_id: string;
  channel_index: number;
  track_id: string;
  channel_label: string;
  side: string | null;
  text: string;
  start: number;
  end: number;
  confidence: number | null;
  words: MultiChannelBatchWord[];
}

export interface MultiChannelBatchChannel {
  channel_index: number;
  track_id: string;
  channel_label: string;
  side: string | null;
  source_kind: string;
  generation: number;
  transcript: string;
  words_count: number;
  segments_count: number;
  average_confidence: number | null;
  segments: MultiChannelBatchSegment[];
  warnings: string[];
}

export interface MultiChannelBatchResult {
  provider: string;
  model: string;
  language: string;
  provider_request_id: string | null;
  sample_rate: number;
  channels_count: number;
  duration_ms: number;
  channels: MultiChannelBatchChannel[];
  chronological_segments: MultiChannelBatchSegment[];
  combined_text: string;
  warnings: string[];
  provider_meta: Record<string, unknown>;
}

export interface MultiChannelBatchComparison {
  available: boolean;
  live_words: number;
  batch_words: number;
  live_chars: number;
  batch_chars: number;
  word_error_rate: number | null;
  text_similarity: number | null;
  channels_with_text: number;
  empty_channels: number[];
  average_confidence: number | null;
  overlap_segments: number;
  overlap_duration_ms: number;
  warnings: string[];
}

export interface MultiChannelBatchJob {
  job_id: string;
  meeting_id: number;
  status: MultiChannelBatchJobStatus;
  stage: string;
  progress: number;
  provider: string;
  model: string;
  language: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  expires_at: string | null;
  result: MultiChannelBatchResult | null;
  comparison: MultiChannelBatchComparison | null;
  export_manifest: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  retryable: boolean;
}

export interface MultiChannelBatchSttRequest {
  export: MultiChannelExportRequest;
  channel_side_overrides?: Record<string, PublicSpeakerSide | null>;
  compare_with_live?: boolean;
}

export async function startMultiChannelBatchStt(
  meetingId: number, body: MultiChannelBatchSttRequest,
): Promise<MultiChannelBatchJob> {
  const { data } = await api.post<MultiChannelBatchJob>(
    `/meetings/${meetingId}/multi-source/batch-stt`, body);
  return data;
}

export async function getMultiChannelBatchSttJob(
  meetingId: number, jobId: string,
): Promise<MultiChannelBatchJob> {
  const { data } = await api.get<MultiChannelBatchJob>(
    `/meetings/${meetingId}/multi-source/batch-stt/${jobId}`);
  return data;
}

export async function cancelMultiChannelBatchSttJob(
  meetingId: number, jobId: string,
): Promise<void> {
  await api.delete(`/meetings/${meetingId}/multi-source/batch-stt/${jobId}`);
}
