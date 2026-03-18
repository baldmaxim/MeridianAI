import api from './client';
import type { UserSettings, ApiKeyInfo } from '../types';

export async function getSettings(): Promise<UserSettings> {
  const { data } = await api.get<UserSettings>('/settings');
  return data;
}

export async function updateSettings(settings: Partial<UserSettings>): Promise<UserSettings> {
  const { data } = await api.put<UserSettings>('/settings', settings);
  return data;
}

export async function getActiveProviders(): Promise<string[]> {
  const { data } = await api.get<{ active_services: string[] }>('/settings/providers');
  return data.active_services;
}

export async function pickFolder(): Promise<string> {
  const { data } = await api.get<{ path: string }>('/settings/pick-folder');
  return data.path;
}

// Admin API key management
export async function listApiKeys(): Promise<ApiKeyInfo[]> {
  const { data } = await api.get<ApiKeyInfo[]>('/admin/api-keys');
  return data;
}

export async function createApiKey(service: string, apiKey: string): Promise<ApiKeyInfo> {
  const { data } = await api.post<ApiKeyInfo>('/admin/api-keys', { service, api_key: apiKey });
  return data;
}

export async function updateApiKey(id: number, updates: { api_key?: string; is_active?: boolean }): Promise<ApiKeyInfo> {
  const { data } = await api.put<ApiKeyInfo>(`/admin/api-keys/${id}`, updates);
  return data;
}

export async function deleteApiKey(id: number): Promise<void> {
  await api.delete(`/admin/api-keys/${id}`);
}
