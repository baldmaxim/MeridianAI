import api from './client';
import type { TranscriptionAuthorityState } from '../types';

export interface AuthoritativeSegmentWire {
  segment_key: string;
  source: string;
  side: string | null;
  speaker: string | null;
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface AuthoritativeTranscriptResponse {
  meeting_id: number;
  available: boolean;
  epochs_count: number;
  sources_used: string[];
  segment_count: number;
  truncated: boolean;
  segments: AuthoritativeSegmentWire[];
}

export async function getTranscriptionAuthorityState(
  meetingId: number,
): Promise<TranscriptionAuthorityState> {
  const { data } = await api.get<TranscriptionAuthorityState>(
    `/meetings/${meetingId}/transcription-authority/state`,
  );
  return data;
}

export async function promoteTranscription(
  meetingId: number, force = false,
): Promise<TranscriptionAuthorityState> {
  const { data } = await api.post<TranscriptionAuthorityState>(
    `/meetings/${meetingId}/transcription-authority/promote`, { force },
  );
  return data;
}

export async function fallbackTranscription(
  meetingId: number,
): Promise<TranscriptionAuthorityState> {
  const { data } = await api.post<TranscriptionAuthorityState>(
    `/meetings/${meetingId}/transcription-authority/fallback`, {},
  );
  return data;
}

export async function getAuthoritativeTranscript(
  meetingId: number,
): Promise<AuthoritativeTranscriptResponse> {
  const { data } = await api.get<AuthoritativeTranscriptResponse>(
    `/meetings/${meetingId}/transcription-authority/transcript`,
  );
  return data;
}
