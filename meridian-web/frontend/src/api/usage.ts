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
