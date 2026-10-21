import axios from 'axios';

/** HTTP-статус ответа axios-ошибки (undefined, если ошибка не axios или ответа нет). */
export const errorStatus = (e: unknown): number | undefined =>
  axios.isAxiosError(e) ? e.response?.status : undefined;

/** Поле detail из тела ответа FastAPI, если это строка. */
export const errorDetail = (e: unknown): string | undefined => {
  if (!axios.isAxiosError(e)) return undefined;
  const detail = (e.response?.data as { detail?: unknown } | undefined)?.detail;
  return typeof detail === 'string' ? detail : undefined;
};

/** Текст сообщения обычной ошибки (Error.message). */
export const errorText = (e: unknown): string | undefined => (e instanceof Error ? e.message : undefined);
