import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listAsrTerms, createAsrTerm, removeAsrTerm } from '../../api/asrTerms';
import type { AsrTermInput } from '../../types';

export const asrTermsKeys = { all: ['asr-terms'] as const };

export function useAsrTerms() {
  return useQuery({ queryKey: asrTermsKeys.all, queryFn: listAsrTerms });
}

export function useCreateAsrTerm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AsrTermInput) => createAsrTerm(input),
    onSuccess: () => qc.invalidateQueries({ queryKey: asrTermsKeys.all }),
  });
}

export function useRemoveAsrTerm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => removeAsrTerm(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: asrTermsKeys.all }),
  });
}
