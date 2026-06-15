import api from './client';
import type { FinalizationStatusInfo, MeetingProtocol, ProtocolPatch } from '../types';

export async function finalizeMeeting(meetingId: number): Promise<FinalizationStatusInfo> {
  const { data } = await api.post<FinalizationStatusInfo>(`/meetings/${meetingId}/finalize`);
  return data;
}

export async function retryFinalization(meetingId: number): Promise<FinalizationStatusInfo> {
  const { data } = await api.post<FinalizationStatusInfo>(`/meetings/${meetingId}/finalization/retry`);
  return data;
}

export async function getFinalizationStatus(meetingId: number): Promise<FinalizationStatusInfo> {
  const { data } = await api.get<FinalizationStatusInfo>(`/meetings/${meetingId}/finalization-status`);
  return data;
}

export async function getMeetingProtocol(meetingId: number): Promise<MeetingProtocol> {
  const { data } = await api.get<MeetingProtocol>(`/meetings/${meetingId}/protocol`);
  return data;
}

export async function updateMeetingProtocol(meetingId: number, patch: ProtocolPatch): Promise<MeetingProtocol> {
  const { data } = await api.patch<MeetingProtocol>(`/meetings/${meetingId}/protocol`, patch);
  return data;
}
