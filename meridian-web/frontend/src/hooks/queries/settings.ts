import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UserSettings } from '../../types';
import { getSettings, updateSettings, getActiveProviders } from '../../api/settings';

export const settingsKeys = {
  user: ['settings', 'user'] as const,
  providers: ['settings', 'providers'] as const,
};

export function useSettings() {
  return useQuery({ queryKey: settingsKeys.user, queryFn: getSettings });
}

export function useActiveProviders() {
  return useQuery({ queryKey: settingsKeys.providers, queryFn: getActiveProviders, staleTime: 5 * 60_000 });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<UserSettings>) => updateSettings(patch),
    onSuccess: (data) => qc.setQueryData(settingsKeys.user, data),
  });
}
