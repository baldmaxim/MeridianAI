// Форматирование и справочники для страницы деталей встречи.

export const NEGOTIATION_TYPE_LABELS: Record<string, string> = {
  sale: 'Продажа',
  claim: 'Претензия',
  negotiation: 'Переговоры',
};

/** label — подпись бейджа; tone — имя CSS-модификатора цвета (см. SuggestionCards.module.css). */
export interface ISuggestionTypeInfo {
  label: string;
  tone: 'priority' | 'counter' | 'question' | 'risk' | 'other';
}

const SUGGESTION_TYPE_LABELS: Record<string, ISuggestionTypeInfo> = {
  priority: { label: 'ПРИОРИТЕТ', tone: 'priority' },
  counter: { label: 'КОНТРАРГУМЕНТ', tone: 'counter' },
  question: { label: 'ВОПРОС', tone: 'question' },
  risk: { label: 'РИСК', tone: 'risk' },
};

export const getSuggestionTypeInfo = (type: string): ISuggestionTypeInfo =>
  SUGGESTION_TYPE_LABELS[type] || { label: type.toUpperCase(), tone: 'other' };

export const formatTime = (iso: string): string => {
  const d = new Date(iso);
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export const formatDateTime = (iso: string): string => {
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
    + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
};

// Длительность = суммарное время записи (диктофон), не время открытой сессии.
export const formatRecorded = (recordedSeconds: number | null | undefined): string | null => {
  if (!recordedSeconds || recordedSeconds <= 0) return null;
  const min = Math.floor(recordedSeconds / 60);
  if (min < 1) return `${recordedSeconds} сек записи`;
  if (min < 60) return `${min} мин записи`;
  return `${Math.floor(min / 60)}ч ${min % 60}м записи`;
};

/** Число цветов в палитре спикеров (speaker0..speaker4 в TranscriptRow.module.css). */
const SPEAKER_PALETTE_SIZE = 5;

/** Стабильный индекс цвета спикера по хэшу имени. */
export const getSpeakerColorIndex = (speaker: string): number => {
  let hash = 0;
  for (let i = 0; i < speaker.length; i++) hash = speaker.charCodeAt(i) + ((hash << 5) - hash);
  return Math.abs(hash) % SPEAKER_PALETTE_SIZE;
};

/** Тон цвета бейджа расширения документа (см. ContextBlock.module.css). */
export const getDocTone = (ext: string): 'pdf' | 'docx' | 'xlsx' | 'other' => {
  switch (ext.toUpperCase()) {
    case 'PDF': return 'pdf';
    case 'DOCX': return 'docx';
    case 'XLSX': return 'xlsx';
    default: return 'other';
  }
};
