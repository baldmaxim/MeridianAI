import api from './client';
import type { SpeakerRoleOut, SpeakerSide } from '../types';

export async function getSpeakerRoles(meetingId: number): Promise<SpeakerRoleOut[]> {
  const { data } = await api.get<SpeakerRoleOut[]>(`/meetings/${meetingId}/speaker-roles`);
  return data;
}

export async function putSpeakerRole(
  meetingId: number, speakerLabel: string,
  body: { side: SpeakerSide | '' | null; display_name?: string | null },
): Promise<SpeakerRoleOut[]> {
  const { data } = await api.put<SpeakerRoleOut[]>(
    `/meetings/${meetingId}/speaker-roles/${encodeURIComponent(speakerLabel)}`, body,
  );
  return data;
}
