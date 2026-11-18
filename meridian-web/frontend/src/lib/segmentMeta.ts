// Язык, перевод и говорящий (диаризация) реплики живой встречи.

const RUSSIAN_CODES = new Set(['ru', 'rus']);
const DIARIZED_RE = /^s(\d+)_speaker_(\d+)$/i;

/** Код языка, который стоит показать бейджем: известный и не русский. */
export const foreignLanguageBadge = (code: string | null | undefined): string | null => {
  const base = (code ?? '').trim().toLowerCase().split('-')[0];
  if (!base || RUSSIAN_CODES.has(base)) return null;
  return base.toUpperCase();
};

/** «s1_speaker_0» → «Спикер 1». В следующих сессиях ElevenLabs номера начинаются заново — добавляем номер сессии. */
export const formatDiarizedSpeaker = (label: string): string => {
  const m = DIARIZED_RE.exec(label.trim());
  if (!m) return label;
  const name = `Спикер ${Number(m[2]) + 1}`;
  return Number(m[1]) > 1 ? `${name} (сессия ${m[1]})` : name;
};

/** Уникальные значения с сохранением порядка. */
export const uniqueInOrder = <T,>(items: T[]): T[] => Array.from(new Set(items));
