import type { IngestTrackInfo } from '../../types';

export const trackLabel = (t: IngestTrackInfo): string => {
  if (t.role === 'primary') return 'Основной';
  if (t.side_hint === 'self') return 'Shadow · Мы';
  if (t.side_hint === 'opponent') return 'Shadow · Не мы';
  return 'Shadow · сторона ?';
};

interface IErrorWithDetail {
  response?: { data?: { detail?: { message?: string } | string } };
}

export const errMessage = (e: unknown): string => {
  const d = (e as IErrorWithDetail)?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && d.message) return d.message;
  return 'Не удалось выполнить экспорт';
};

export const STAGE_LABELS: Record<string, string> = {
  queued: 'В очереди',
  preparing: 'Подготовка и сборка WAV',
  transcribing: 'Отправка в STT',
  parsing: 'Обработка ответа',
  comparing: 'Сравнение',
  succeeded: 'Готово',
};

export const friendlyError = (code: string | null, message: string | null): string | null => {
  if (!code) return null;
  if (code === 'PROVIDER_AUTH' || code === 'PROVIDER_NOT_CONFIGURED') return 'STT-провайдер не настроен';
  if (code === 'PROVIDER_TIMEOUT') return 'Провайдер не успел обработать запись';
  if (code === 'PROVIDER_RATE_LIMIT') return 'Лимит STT-провайдера исчерпан. Повторите позже';
  return message || 'Ошибка распознавания каналов';
};

export const fmtTs = (sec: number): string => {
  const m = Math.floor(sec / 60);
  const rest = sec - m * 60;
  return `${String(m).padStart(2, '0')}:${rest.toFixed(1).padStart(4, '0')}`;
};
