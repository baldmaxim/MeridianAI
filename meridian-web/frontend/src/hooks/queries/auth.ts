import { useQuery } from '@tanstack/react-query';
import { getMe } from '../../api/auth';

export const authKeys = {
  me: ['auth', 'me'] as const,
};

// getMe дёргается из нескольких мест — единый кэш убирает дубль-запросы /auth/me.
// enabled: грузим только если есть токен (на странице логина не дёргаем).
export function useMe(enabled = true) {
  return useQuery({
    queryKey: authKeys.me,
    queryFn: getMe,
    staleTime: 5 * 60_000,
    enabled,
  });
}
