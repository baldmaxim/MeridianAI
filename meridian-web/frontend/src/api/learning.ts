import api from './client';
import type { LearningCandidate, LearningCandidateType } from '../types';

export interface CandidateFilters {
  status?: string;
  candidate_type?: LearningCandidateType;
  meeting_id?: number;
  customer_id?: number;
  object_id?: number;
}

export async function listCandidates(filters: CandidateFilters = {}): Promise<LearningCandidate[]> {
  const { data } = await api.get<LearningCandidate[]>('/learning/candidates', { params: filters });
  return data;
}

export async function getCandidate(id: number): Promise<LearningCandidate> {
  const { data } = await api.get<LearningCandidate>(`/learning/candidates/${id}`);
  return data;
}

export interface CandidatePatch {
  title?: string;
  payload?: Record<string, unknown>;
  source_text?: string;
  confidence?: number;
}

export async function patchCandidate(id: number, patch: CandidatePatch): Promise<LearningCandidate> {
  const { data } = await api.patch<LearningCandidate>(`/learning/candidates/${id}`, patch);
  return data;
}

export async function approveCandidate(id: number): Promise<LearningCandidate> {
  const { data } = await api.post<LearningCandidate>(`/learning/candidates/${id}/approve`);
  return data;
}

export async function rejectCandidate(id: number): Promise<LearningCandidate> {
  const { data } = await api.post<LearningCandidate>(`/learning/candidates/${id}/reject`);
  return data;
}

export async function triggerExtraction(meetingId: number): Promise<{ status: string; meeting_id: number }> {
  const { data } = await api.post(`/meetings/${meetingId}/learning/extract`);
  return data;
}
