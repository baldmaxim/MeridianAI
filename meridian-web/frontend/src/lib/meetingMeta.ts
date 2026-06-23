// Общие метаданные встреч для списков/карточек (вынесено из HistoryPage, чтобы не дублировать).
import type { FinalizationStatus } from '../types';

export const FIN_LABELS: Record<string, string> = {
  queued: 'сохраняется', running: 'протокол…', completed: 'протокол готов',
  partial: 'протокол частично', error: 'ошибка протокола',
};

export function finBadgeStyle(s: FinalizationStatus): React.CSSProperties {
  const color = s === 'completed' ? '#2EE59D' : s === 'error' ? '#FF4B6E'
    : s === 'partial' ? '#F5A623' : '#5B9CF6';
  return {
    padding: '2px 8px', background: 'transparent', border: `1px solid ${color}`,
    borderRadius: 4, fontFamily: "'JetBrains Mono', monospace", fontSize: 9,
    color, letterSpacing: '0.04em',
  };
}

// Длительность = суммарное время записи (диктофон), не время открытой сессии.
export function formatDuration(recordedSeconds: number | null | undefined): string {
  if (!recordedSeconds || recordedSeconds <= 0) return '--';
  const min = Math.floor(recordedSeconds / 60);
  if (min < 1) return `${recordedSeconds} сек`;
  if (min < 60) return `${min} мин`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}ч ${m}м`;
}
