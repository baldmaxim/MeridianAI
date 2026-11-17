import api from './client';

export interface IElevenLabsUsage {
  used: number;
  limit: number;
  remaining: number;
  percent_used: number;
  /** Дата сброса кредитов, YYYY-MM-DD (UTC), либо null */
  next_reset: string | null;
}

export const getElevenLabsUsage = async (): Promise<IElevenLabsUsage> => {
  const { data } = await api.get<IElevenLabsUsage>('/usage/elevenlabs');
  return data;
};

export interface IOpenRouterUsage {
  /** Всего кредитов (или лимит ключа), $; null — лимита нет */
  total: number | null;
  /** Израсходовано, $ */
  used: number;
  /** Остаток, $; null — если total неизвестен */
  remaining: number | null;
  percent_used: number;
}

/** Только для админа (иначе 403) */
export const getOpenRouterUsage = async (): Promise<IOpenRouterUsage> => {
  const { data } = await api.get<IOpenRouterUsage>('/usage/openrouter');
  return data;
};
