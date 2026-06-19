import { QueryClient } from '@tanstack/react-query';

// Единый клиент кэша для всего портала.
// staleTime > 0 + gcTime: повторный заход/переключение вкладки красятся мгновенно из кэша,
// рефетч идёт фоном (stale-while-revalidate). Кэш только в памяти (без localStorage — PII).
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000, // 1 мин — в этом окне mount не ходит в сеть
      gcTime: 10 * 60_000, // кэш живёт 10 мин после размонтирования → instant remount
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});
