import api from './client';
import type { ProjectObject, ObjectAccessGrant, GranteeType, AccessLevel } from '../types';

export interface ProjectObjectInput {
  customer_id: number;
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

// --- Доступ к объекту ---

export interface ObjectAccessInput {
  grantee_type: GranteeType;
  grantee_user_id?: number | null;
  grantee_department_id?: number | null;
  access_level?: AccessLevel;
}

export async function listObjectAccess(objectId: number): Promise<ObjectAccessGrant[]> {
  const { data } = await api.get<ObjectAccessGrant[]>(`/objects/${objectId}/access`);
  return data;
}

export async function createObjectAccess(objectId: number, input: ObjectAccessInput): Promise<ObjectAccessGrant> {
  const { data } = await api.post<ObjectAccessGrant>(`/objects/${objectId}/access`, input);
  return data;
}

export async function deleteObjectAccess(objectId: number, grantId: number): Promise<void> {
  await api.delete(`/objects/${objectId}/access/${grantId}`);
}
