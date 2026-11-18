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
  /** Остаток, $: по лимиту ключа либо баланс аккаунта; null — неизвестен */
  balance: number | null;
  /** Откуда остаток: лимит ключа или баланс аккаунта */
  source: 'key' | 'account' | null;
}

/** Только для админа (иначе 403) */
export const getOpenRouterUsage = async (): Promise<IOpenRouterUsage> => {
  const { data } = await api.get<IOpenRouterUsage>('/usage/openrouter');
  return data;
};
