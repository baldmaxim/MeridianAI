import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { PageAccessConfig } from '../../types';
import { listUsers, updateUser, deleteUser, type UserPatch } from '../../api/users';
import { listApiKeys, createApiKey, updateApiKey, deleteApiKey, testLmStudio } from '../../api/settings';
import { getPageAccess, updatePageAccess } from '../../api/pageAccess';

export const adminKeys = {
  users: ['admin', 'users'] as const,
  apiKeys: ['admin', 'api-keys'] as const,
  pageAccess: ['admin', 'page-access'] as const,
};

// --- пользователи ---

export function useUsers() {
  return useQuery({ queryKey: adminKeys.users, queryFn: listUsers });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: UserPatch }) => updateUser(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.users }),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.users }),
  });
}

// --- API-ключи ---

export function useApiKeys() {
  return useQuery({ queryKey: adminKeys.apiKeys, queryFn: listApiKeys });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ service, apiKey }: { service: string; apiKey: string }) => createApiKey(service, apiKey),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.apiKeys }),
  });
}

export function useUpdateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, updates }: { id: number; updates: { api_key?: string; is_active?: boolean } }) =>
      updateApiKey(id, updates),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.apiKeys }),
  });
}

export function useDeleteApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteApiKey(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.apiKeys }),
  });
}

export function useTestLmStudio() {
  return useMutation({ mutationFn: () => testLmStudio() });
}

// --- доступ к страницам ---

export function usePageAccess() {
  return useQuery({ queryKey: adminKeys.pageAccess, queryFn: getPageAccess });
}

export function useUpdatePageAccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ role, allowedPages }: { role: string; allowedPages: string[] }) =>
      updatePageAccess(role, allowedPages),
    // оптимистично: галочка переключается мгновенно, при ошибке — откат
    onMutate: async ({ role, allowedPages }) => {
      await qc.cancelQueries({ queryKey: adminKeys.pageAccess });
      const prev = qc.getQueryData<PageAccessConfig>(adminKeys.pageAccess);
      if (prev) {
        qc.setQueryData<PageAccessConfig>(adminKeys.pageAccess, {
          ...prev,
          roles: prev.roles.map((r) =>
            r.role_name === role ? { ...r, allowed_pages: allowedPages } : r),
        });
      }
      return { prev };
    },
    onError: (_e, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(adminKeys.pageAccess, ctx.prev);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: adminKeys.pageAccess }),
  });
}
