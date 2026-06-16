import api from './client';
import type { PageAccessConfig, RolePageAccess } from '../types';

// Матрица доступа к страницам (admin-only эндпоинты).
export async function getPageAccess(): Promise<PageAccessConfig> {
  const { data } = await api.get<PageAccessConfig>('/admin/page-access');
  return data;
}

export async function updatePageAccess(role: string, allowedPages: string[]): Promise<RolePageAccess> {
  const { data } = await api.put<RolePageAccess>(`/admin/page-access/${role}`, { allowed_pages: allowedPages });
  return data;
}
