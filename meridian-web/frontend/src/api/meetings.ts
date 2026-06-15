import api, { API_BASE } from './client';
import type { TranscriptionRecord, MeetingParticipant } from '../types';

export async function saveTranscription(filename: string, format: 'txt' | 'json'): Promise<TranscriptionRecord> {
  const { data } = await api.post<TranscriptionRecord>('/transcriptions/save', { filename, format });
  return data;
}

export async function listTranscriptions(): Promise<TranscriptionRecord[]> {
  const { data } = await api.get<TranscriptionRecord[]>('/transcriptions');
  return data;
}

export function getDownloadUrl(id: number): string {
  const token = localStorage.getItem('token');
  return `${API_BASE}/transcriptions/${id}/download?token=${token}`;
}

// --- Этап 1 MVP: создание/обновление встречи (REST draft) ---

export interface MeetingDraftInput {
  title?: string | null;
  customer_id?: number | null;
  object_id?: number | null;
  meeting_topic?: string | null;
  meeting_notes?: string | null;
  negotiation_type?: string | null;
  meeting_role?: string | null;
  opponent_weaknesses?: string | null;
}

export interface MeetingDraft {
  id: number;
  customer_id: number | null;
  object_id: number | null;
  status: string | null;
  is_active: boolean;
}

export async function createMeeting(input: MeetingDraftInput): Promise<MeetingDraft> {
  const { data } = await api.post<MeetingDraft>('/meetings', input);
  return data;
}

export async function updateMeeting(id: number, input: Partial<MeetingDraftInput> & { status?: string }): Promise<MeetingDraft> {
  const { data } = await api.patch<MeetingDraft>(`/meetings/${id}`, input);
  return data;
}

// --- Участники встречи ---

export async function listParticipants(meetingId: number): Promise<MeetingParticipant[]> {
  const { data } = await api.get<MeetingParticipant[]>(`/meetings/${meetingId}/participants`);
  return data;
}

export async function addParticipant(meetingId: number, userId: number, role = 'participant'): Promise<MeetingParticipant> {
  const { data } = await api.post<MeetingParticipant>(`/meetings/${meetingId}/participants/${userId}`, null, { params: { role } });
  return data;
}

export async function removeParticipant(meetingId: number, userId: number): Promise<void> {
  await api.delete(`/meetings/${meetingId}/participants/${userId}`);
}
