import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getBatchJobs, getBatchJob, uploadBatchAudio, deleteBatchJob, createBatchFromStash } from '../../api/batch';

export const batchKeys = {
  jobs: ['batch', 'jobs'] as const,
  job: (id: number) => ['batch', 'job', id] as const,
};

// polling каждые 5с — статусы задач меняются по мере обработки
export function useBatchJobs() {
  return useQuery({ queryKey: batchKeys.jobs, queryFn: getBatchJobs, refetchInterval: 5000 });
}

export function useBatchJob(id: number | null) {
  return useQuery({
    queryKey: batchKeys.job(id ?? 0),
    queryFn: () => getBatchJob(id as number),
    enabled: id != null,
    // polling 3с, пока задача в работе; стоп на done/error
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === 'done' || s === 'error' ? false : 3000;
    },
  });
}

export function useUploadBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadBatchAudio(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: batchKeys.jobs }),
  });
}

export function useDeleteBatchJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteBatchJob(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: batchKeys.jobs }),
  });
}

export function useCreateBatchFromStash() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fileId: number) => createBatchFromStash(fileId),
    onSuccess: () => qc.invalidateQueries({ queryKey: batchKeys.jobs }),
  });
}
