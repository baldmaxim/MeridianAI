import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listCandidates, approveCandidate, rejectCandidate, patchCandidate,
  type CandidatePatch,
} from '../../api/learning';

export const learningKeys = {
  all: ['learning', 'candidates'] as const,
  list: (meetingId: number | null | undefined, status: string) =>
    ['learning', 'candidates', { meetingId: meetingId ?? null, status }] as const,
};

export function useCandidates(meetingId?: number | null, status = 'pending') {
  return useQuery({
    queryKey: learningKeys.list(meetingId, status),
    queryFn: () => listCandidates({ status, ...(meetingId != null ? { meeting_id: meetingId } : {}) }),
  });
}

function useCandidatesInvalidator() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: learningKeys.all });
}

export function useApproveCandidate() {
  const invalidate = useCandidatesInvalidator();
  return useMutation({ mutationFn: (id: number) => approveCandidate(id), onSuccess: invalidate });
}

export function useRejectCandidate() {
  const invalidate = useCandidatesInvalidator();
  return useMutation({ mutationFn: (id: number) => rejectCandidate(id), onSuccess: invalidate });
}

export function usePatchCandidate() {
  const invalidate = useCandidatesInvalidator();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: CandidatePatch }) => patchCandidate(id, patch),
    onSuccess: invalidate,
  });
}
