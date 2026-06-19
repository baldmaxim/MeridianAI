import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { AISettingsProfile, AISettingsProfileInput } from '../../types';
import {
  listProfiles, createProfile, updateProfile, deleteProfile, makeDefaultProfile, getOptions,
} from '../../api/aiSettings';

export const aiSettingsKeys = {
  profiles: ['ai-settings', 'profiles'] as const,
  options: ['ai-settings', 'options'] as const,
};

export function useProfiles() {
  return useQuery({ queryKey: aiSettingsKeys.profiles, queryFn: listProfiles });
}

// опции (списки провайдеров/моделей) меняются редко — длинный staleTime
export function useAiOptions() {
  return useQuery({ queryKey: aiSettingsKeys.options, queryFn: getOptions, staleTime: 5 * 60_000 });
}

export function useCreateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AISettingsProfileInput) => createProfile(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: aiSettingsKeys.profiles }),
  });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: AISettingsProfileInput }) => updateProfile(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: aiSettingsKeys.profiles }),
  });
}

export function useDeleteProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteProfile(id),
    // оптимистично убрать строку из списка
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: aiSettingsKeys.profiles });
      const prev = qc.getQueryData<AISettingsProfile[]>(aiSettingsKeys.profiles);
      if (prev) qc.setQueryData(aiSettingsKeys.profiles, prev.filter((p) => p.id !== id));
      return { prev };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(aiSettingsKeys.profiles, ctx.prev);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: aiSettingsKeys.profiles }),
  });
}

export function useMakeDefaultProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => makeDefaultProfile(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: aiSettingsKeys.profiles }),
  });
}
