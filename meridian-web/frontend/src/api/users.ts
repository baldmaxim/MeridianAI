import api from './client';
import type { User } from '../types';

/** Список пользователей (для пикеров доступа/отделов). Требует роли admin. */
export async function listUsers(): Promise<User[]> {
  const { data } = await api.get<User[]>('/admin/users');
  return data;
}
