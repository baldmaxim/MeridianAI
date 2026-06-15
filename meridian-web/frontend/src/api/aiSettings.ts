import api from './client';
import type {
  AISettingsProfile, AISettingsProfileInput, AISettingsOptions,
  MeetingAISettings, MeetingAISettingsPatch,
} from '../types';

// --- профили ---

export async function listProfiles(): Promise<AISettingsProfile[]> {
  const { data } = await api.get<AISettingsProfile[]>('/ai-settings/profiles');
  return data;
}

export async function getProfile(id: number): Promise<AISettingsProfile> {
  const { data } = await api.get<AISettingsProfile>(`/ai-settings/profiles/${id}`);
  return data;
}

export async function createProfile(body: AISettingsProfileInput): Promise<AISettingsProfile> {
  const { data } = await api.post<AISettingsProfile>('/ai-settings/profiles', body);
  return data;
}

export async function updateProfile(id: number, body: AISettingsProfileInput): Promise<AISettingsProfile> {
  const { data } = await api.put<AISettingsProfile>(`/ai-settings/profiles/${id}`, body);
  return data;
}

export async function deleteProfile(id: number): Promise<void> {
  await api.delete(`/ai-settings/profiles/${id}`);
}

export async function makeDefaultProfile(id: number): Promise<AISettingsProfile> {
  const { data } = await api.post<AISettingsProfile>(`/ai-settings/profiles/${id}/make-default`);
  return data;
}

export async function getOptions(): Promise<AISettingsOptions> {
  const { data } = await api.get<AISettingsOptions>('/ai-settings/options');
  return data;
}

// --- настройки встречи ---

export async function getMeetingAISettings(meetingId: number): Promise<MeetingAISettings> {
  const { data } = await api.get<MeetingAISettings>(`/meetings/${meetingId}/ai-settings`);
  return data;
}

export async function patchMeetingAISettings(
  meetingId: number, patch: MeetingAISettingsPatch,
): Promise<MeetingAISettings> {
  const { data } = await api.patch<MeetingAISettings>(`/meetings/${meetingId}/ai-settings`, patch);
  return data;
}

export async function applyProfileToMeeting(meetingId: number, profileId: number): Promise<MeetingAISettings> {
  const { data } = await api.post<MeetingAISettings>(
    `/meetings/${meetingId}/ai-settings/apply-profile/${profileId}`);
  return data;
}
