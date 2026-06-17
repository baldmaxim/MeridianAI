import api from './client';
import type { User } from '../types';

/** Список пользователей (для пикеров доступа/отделов). Требует роли admin. */
export async function listUsers(): Promise<User[]> {
  const { data } = await api.get<User[]>('/admin/users');
  return data;
}

export interface UserPatch {
  display_name?: string | null;
  role?: 'user' | 'admin';
  is_active?: boolean;
  password?: string;
}

/** Частичное обновление пользователя админом. */
export async function updateUser(id: number, patch: UserPatch): Promise<User> {
  const { data } = await api.put<User>(`/admin/users/${id}`, patch);
  return data;
}

/** Жёсткое удаление пользователя (каскадно сотрёт все его данные). */
export async function deleteUser(id: number): Promise<void> {
  await api.delete(`/admin/users/${id}`);
}
