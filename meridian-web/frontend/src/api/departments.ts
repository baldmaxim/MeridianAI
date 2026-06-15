import api from './client';
import type { Department, DepartmentUser } from '../types';

export interface DepartmentInput {
  name: string;
  description?: string | null;
}

export async function listDepartments(): Promise<Department[]> {
  const { data } = await api.get<Department[]>('/departments');
  return data;
}

export async function getDepartment(id: number): Promise<Department> {
  const { data } = await api.get<Department>(`/departments/${id}`);
  return data;
}

export async function createDepartment(input: DepartmentInput): Promise<Department> {
  const { data } = await api.post<Department>('/departments', input);
  return data;
}

export async function updateDepartment(id: number, input: Partial<DepartmentInput>): Promise<Department> {
  const { data } = await api.put<Department>(`/departments/${id}`, input);
  return data;
}

export async function deleteDepartment(id: number): Promise<void> {
  await api.delete(`/departments/${id}`);
}

// --- Сотрудники отдела ---

export async function listDepartmentUsers(departmentId: number): Promise<DepartmentUser[]> {
  const { data } = await api.get<DepartmentUser[]>(`/departments/${departmentId}/users`);
  return data;
}

export async function addDepartmentUser(departmentId: number, userId: number): Promise<DepartmentUser> {
  const { data } = await api.post<DepartmentUser>(`/departments/${departmentId}/users/${userId}`);
  return data;
}

export async function removeDepartmentUser(departmentId: number, userId: number): Promise<void> {
  await api.delete(`/departments/${departmentId}/users/${userId}`);
}
