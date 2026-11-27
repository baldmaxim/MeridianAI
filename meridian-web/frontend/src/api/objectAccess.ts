import api from './client';

export interface IObjectAccess {
  all_objects: boolean;
  customer_ids: number[];
  object_ids: number[];
}

export type ObjectAccessRequestStatus = 'pending' | 'approved' | 'rejected';

export interface IObjectAccessRequest {
  id: number;
  user_id: number;
  user_email: string;
  user_display_name: string | null;
  object_id: number;
  object_name: string;
  customer_name: string;
  status: ObjectAccessRequestStatus;
  created_at: string;
}

export interface IAccessRequestResult {
  status: 'pending' | 'already_granted';
}

export interface IDuplicateCandidate {
  id: number;
  name: string;
  customer_name: string;
  has_access: boolean;
}

/** Тело detail ответа 409 на POST /objects. */
export interface IDuplicateObjectDetail {
  code: 'duplicate_object';
  exact: boolean;
  candidates: IDuplicateCandidate[];
}

export async function getUserObjectAccess(userId: number): Promise<IObjectAccess> {
  const { data } = await api.get<IObjectAccess>(`/admin/users/${userId}/object-access`);
  return data;
}

export async function setUserObjectAccess(userId: number, access: IObjectAccess): Promise<IObjectAccess> {
  const { data } = await api.put<IObjectAccess>(`/admin/users/${userId}/object-access`, access);
  return data;
}

export async function listObjectAccessRequests(status: ObjectAccessRequestStatus = 'pending'): Promise<IObjectAccessRequest[]> {
  const { data } = await api.get<IObjectAccessRequest[]>('/admin/object-access-requests', { params: { status } });
  return data;
}

export async function approveObjectAccessRequest(id: number): Promise<{ status: string }> {
  const { data } = await api.post<{ status: string }>(`/admin/object-access-requests/${id}/approve`);
  return data;
}

export async function rejectObjectAccessRequest(id: number): Promise<{ status: string }> {
  const { data } = await api.post<{ status: string }>(`/admin/object-access-requests/${id}/reject`);
  return data;
}

export async function requestObjectAccess(objectId: number): Promise<IAccessRequestResult> {
  const { data } = await api.post<IAccessRequestResult>(`/objects/${objectId}/access-request`);
  return data;
}
