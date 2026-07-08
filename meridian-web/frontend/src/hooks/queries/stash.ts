import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getStashFiles, uploadStashFile, deleteStashFile } from '../../api/stash';

export const stashKeys = {
  files: ['stash', 'files'] as const,
};

// polling 15с — чтобы загруженное с другого устройства появлялось без ручного обновления
export function useStashFiles() {
  return useQuery({ queryKey: stashKeys.files, queryFn: getStashFiles, refetchInterval: 15000 });
}

export function useUploadStash() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { file: File; onProgress?: (frac: number) => void }) =>
      uploadStashFile(args.file, args.onProgress),
    onSuccess: () => qc.invalidateQueries({ queryKey: stashKeys.files }),
  });
}

export function useDeleteStash() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteStashFile(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: stashKeys.files }),
  });
}
