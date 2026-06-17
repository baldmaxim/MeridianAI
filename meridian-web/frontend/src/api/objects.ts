import api from './client';
import type { ProjectObject } from '../types';

export interface ProjectObjectInput {
  customer_name: string;
  name: string;
  address?: string | null;
  description?: string | null;
  notes?: string | null;
  is_active?: boolean;
}

export async function listObjects(customerId?: number): Promise<ProjectObject[]> {
  const { data } = await api.get<ProjectObject[]>('/objects', {
    params: customerId != null ? { customer_id: customerId } : undefined,
  });
  return data;
}

export async function getObject(id: number): Promise<ProjectObject> {
  const { data } = await api.get<ProjectObject>(`/objects/${id}`);
  return data;
}

export async function createObject(input: ProjectObjectInput): Promise<ProjectObject> {
  const { data } = await api.post<ProjectObject>('/objects', input);
  return data;
}

export async function updateObject(id: number, input: Partial<ProjectObjectInput>): Promise<ProjectObject> {
  const { data } = await api.put<ProjectObject>(`/objects/${id}`, input);
  return data;
}

export async function deleteObject(id: number): Promise<void> {
  await api.delete(`/objects/${id}`);
}
