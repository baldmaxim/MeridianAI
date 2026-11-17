import api from './client';
import type { AsrTerm, AsrTermInput } from '../types';

export async function listAsrTerms(): Promise<AsrTerm[]> {
  const { data } = await api.get<AsrTerm[]>('/asr-terms');
  return data;
}

export async function createAsrTerm(input: AsrTermInput): Promise<AsrTerm> {
  const { data } = await api.post<AsrTerm>('/asr-terms', input);
  return data;
}

export async function removeAsrTerm(id: number): Promise<void> {
  await api.delete(`/asr-terms/${id}`);
}
