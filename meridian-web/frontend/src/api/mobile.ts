import api from './client';
import type { MobileMeetingListItem, MobileMeetingDetail, LiveState } from '../types';

export interface MobileFilters {
  status?: string;
  customer_id?: number;
  object_id?: number;
  q?: string;
  only_live?: boolean;
}

export async function listMobileMeetings(filters?: MobileFilters): Promise<MobileMeetingListItem[]> {
  const params: Record<string, string | number | boolean> = {};
  if (filters?.status) params.status = filters.status;
  if (filters?.customer_id != null) params.customer_id = filters.customer_id;
  if (filters?.object_id != null) params.object_id = filters.object_id;
  if (filters?.q) params.q = filters.q;
  if (filters?.only_live) params.only_live = true;
  const { data } = await api.get<MobileMeetingListItem[]>('/mobile/meetings', { params });
  return data;
}

export async function getMobileMeeting(id: number): Promise<MobileMeetingDetail> {
  const { data } = await api.get<MobileMeetingDetail>(`/mobile/meetings/${id}`);
  return data;
}

export async function getLiveState(meetingId: number): Promise<LiveState> {
  const { data } = await api.get<LiveState>(`/meetings/${meetingId}/live-state`);
  return data;
}
