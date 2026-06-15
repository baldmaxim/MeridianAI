import api from './client';
import type {
  MeetingContextSource, PreviousMeetingCandidate,
  MeetingContextSourceCreate, MeetingContextSourceUpdate,
} from '../types';

export interface CandidateFilters {
  customer_id?: number;
  object_id?: number;
  q?: string;
  limit?: number;
  include_finalized_only?: boolean;
}

export async function listContextCandidates(
  meetingId: number, filters: CandidateFilters = {},
): Promise<PreviousMeetingCandidate[]> {
  const { data } = await api.get<PreviousMeetingCandidate[]>(
    `/meetings/${meetingId}/context-candidates`, { params: filters });
  return data;
}

export async function listContextSources(meetingId: number): Promise<MeetingContextSource[]> {
  const { data } = await api.get<MeetingContextSource[]>(`/meetings/${meetingId}/context-sources`);
  return data;
}

export async function addContextSource(
  meetingId: number, body: MeetingContextSourceCreate,
): Promise<MeetingContextSource> {
  const { data } = await api.post<MeetingContextSource>(`/meetings/${meetingId}/context-sources`, body);
  return data;
}

export async function updateContextSource(
  meetingId: number, sourceId: number, body: MeetingContextSourceUpdate,
): Promise<MeetingContextSource> {
  const { data } = await api.patch<MeetingContextSource>(
    `/meetings/${meetingId}/context-sources/${sourceId}`, body);
  return data;
}

export async function deleteContextSource(meetingId: number, sourceId: number): Promise<void> {
  await api.delete(`/meetings/${meetingId}/context-sources/${sourceId}`);
}
