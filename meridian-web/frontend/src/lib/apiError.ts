import { AxiosError } from 'axios';

/** Достаёт человекочитаемое сообщение из ошибки FastAPI (detail) или axios. */
export function apiErrorMessage(err: unknown, fallback = 'Ошибка'): string {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length && detail[0]?.msg) return detail[0].msg;
    if (err.message) return err.message;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}
