import api from './client';
import type { NegotiationRole } from '../types';

export async function getRoles(): Promise<NegotiationRole[]> {
  const { data } = await api.get<NegotiationRole[]>('/roles');
  return data;
}

export async function createRole(
  role: Omit<NegotiationRole, 'id' | 'is_default' | 'created_at'>
): Promise<NegotiationRole> {
  const { data } = await api.post<NegotiationRole>('/roles', role);
  return data;
}

export async function updateRole(
  id: number,
  updates: Partial<Omit<NegotiationRole, 'id' | 'is_default' | 'created_at'>>
): Promise<NegotiationRole> {
  const { data } = await api.put<NegotiationRole>(`/roles/${id}`, updates);
  return data;
}

export async function deleteRole(id: number): Promise<void> {
  await api.delete(`/roles/${id}`);
}
