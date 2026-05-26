import api, { API_BASE } from './client';
import type { TranscriptionRecord } from '../types';

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
