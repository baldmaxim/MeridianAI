import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import {
  listMeetings, getMeetingDetail, batchDeleteMeetings, deleteMeeting,
  updateMeetingTitle, continueMeeting, type MeetingFilters,
} from '../../api/history';
import { finalizeMeeting, retryFinalization } from '../../api/finalization';

// Списки/детали встреч под ['meetings', ...].
// Meeting-scoped под-ресурсы (Tier 3) живут под ['meeting', id, ...] (singular) — не пересекаются.
export const meetingKeys = {
  all: ['meetings'] as const,
  list: (filters: MeetingFilters) => ['meetings', 'list', filters] as const,
  detail: (id: number) => ['meetings', 'detail', id] as const,
};

export function useMeetingsList(filters: MeetingFilters = {}) {
  return useQuery({
    queryKey: meetingKeys.list(filters),
    queryFn: () => listMeetings(filters),
    placeholderData: keepPreviousData, // не моргать при смене фильтра
  });
}

export function useMeetingDetail(id: number | null) {
  return useQuery({
    queryKey: meetingKeys.detail(id ?? 0),
    queryFn: () => getMeetingDetail(id as number),
    enabled: id != null,
  });
}

function useMeetingsInvalidator() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: meetingKeys.all });
}

export function useFinalizeMeeting() {
  const invalidate = useMeetingsInvalidator();
  return useMutation({ mutationFn: (id: number) => finalizeMeeting(id), onSuccess: invalidate });
}

export function useRetryFinalization() {
  const invalidate = useMeetingsInvalidator();
  return useMutation({ mutationFn: (id: number) => retryFinalization(id), onSuccess: invalidate });
}

export function useBatchDeleteMeetings() {
  const invalidate = useMeetingsInvalidator();
  return useMutation({ mutationFn: (ids: number[]) => batchDeleteMeetings(ids), onSuccess: invalidate });
}

export function useDeleteMeeting() {
  const invalidate = useMeetingsInvalidator();
  return useMutation({ mutationFn: (id: number) => deleteMeeting(id), onSuccess: invalidate });
}

export function useUpdateMeetingTitle() {
  const invalidate = useMeetingsInvalidator();
  return useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) => updateMeetingTitle(id, title),
    onSuccess: invalidate,
  });
}

export function useContinueMeeting() {
  const invalidate = useMeetingsInvalidator();
  return useMutation({ mutationFn: (id: number) => continueMeeting(id), onSuccess: invalidate });
}
