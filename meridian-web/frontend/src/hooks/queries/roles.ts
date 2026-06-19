import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { NegotiationRole } from '../../types';
import { getRoles, createRole, updateRole, deleteRole } from '../../api/roles';

type RoleInput = Omit<NegotiationRole, 'id' | 'is_default' | 'created_at'>;

export const rolesKeys = { all: ['roles'] as const };

export function useRoles() {
  return useQuery({ queryKey: rolesKeys.all, queryFn: getRoles });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (role: RoleInput) => createRole(role),
    onSuccess: () => qc.invalidateQueries({ queryKey: rolesKeys.all }),
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, updates }: { id: number; updates: Partial<RoleInput> }) => updateRole(id, updates),
    onSuccess: () => qc.invalidateQueries({ queryKey: rolesKeys.all }),
  });
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteRole(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: rolesKeys.all }),
  });
}
