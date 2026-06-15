import api from './client';
import type { MeetingDocument } from '../types';

export async function listMeetingDocuments(meetingId: number): Promise<MeetingDocument[]> {
  const { data } = await api.get<MeetingDocument[]>(`/meetings/${meetingId}/documents`);
  return data;
}

export async function attachMeetingDocument(meetingId: number, documentId: number): Promise<MeetingDocument> {
  const { data } = await api.post<MeetingDocument>(`/meetings/${meetingId}/documents/${documentId}`);
  return data;
}

export async function patchMeetingDocument(
  meetingId: number,
  documentId: number,
  patch: { included?: boolean; priority?: number },
): Promise<MeetingDocument> {
  const { data } = await api.patch<MeetingDocument>(`/meetings/${meetingId}/documents/${documentId}`, patch);
  return data;
}

export async function detachMeetingDocument(meetingId: number, documentId: number): Promise<void> {
  await api.delete(`/meetings/${meetingId}/documents/${documentId}`);
}
