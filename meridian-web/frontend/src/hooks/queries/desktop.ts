import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listDevices, revokeDevice } from '../../api/desktop';

export const desktopKeys = {
  devices: ['desktop', 'devices'] as const,
};

export function useDesktopDevices() {
  return useQuery({ queryKey: desktopKeys.devices, queryFn: listDevices });
}

export function useRevokeDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => revokeDevice(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: desktopKeys.devices }),
  });
}
