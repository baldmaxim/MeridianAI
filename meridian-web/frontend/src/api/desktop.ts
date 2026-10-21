import api from './client';

export interface IDesktopDevice {
  id: number;
  name: string;
  platform: string | null;
  app_version: string | null;
  created_at: string | null;
  last_seen_at: string | null;
}

export async function listDevices(): Promise<IDesktopDevice[]> {
  const { data } = await api.get<IDesktopDevice[]>('/desktop/devices');
  return data;
}

export async function revokeDevice(id: number): Promise<void> {
  await api.delete(`/desktop/devices/${id}`);
}
