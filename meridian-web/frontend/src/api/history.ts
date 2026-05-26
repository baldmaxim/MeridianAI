import api from './client';
import type { MeetingListItem, MeetingDetail } from '../types';

export async function listMeetings(): Promise<MeetingListItem[]> {
  const { data } = await api.get<MeetingListItem[]>('/meetings');
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
