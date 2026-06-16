import api from './client';
import type { MeetingListItem, MeetingDetail } from '../types';

export interface MeetingFilters {
  customer_id?: number;
  object_id?: number;
  status?: string;
  q?: string;
  include_active?: boolean;
}

export async function listMeetings(filters?: MeetingFilters): Promise<MeetingListItem[]> {
  const params: Record<string, string | number | boolean> = {};
  if (filters?.customer_id != null) params.customer_id = filters.customer_id;
  if (filters?.object_id != null) params.object_id = filters.object_id;
  if (filters?.status) params.status = filters.status;
  if (filters?.q) params.q = filters.q;
  if (filters?.include_active) params.include_active = true;
  const { data } = await api.get<MeetingListItem[]>('/meetings', { params });
  return data;
}

export async function getMeetingDetail(id: number): Promise<MeetingDetail> {
  const { data } = await api.get<MeetingDetail>(`/meetings/${id}`);
  return data;
}

export async function updateMeetingTitle(id: number, title: string): Promise<void> {
  await api.put(`/meetings/${id}/title`, { title });
}

export async function continueMeeting(id: number): Promise<void> {
  await api.post(`/meetings/${id}/continue`);
}

export async function batchDeleteMeetings(ids: number[]): Promise<void> {
  await api.post('/meetings/batch/delete', { ids });
}

export async function deleteMeeting(id: number): Promise<void> {
  await api.delete(`/meetings/${id}`);
}
