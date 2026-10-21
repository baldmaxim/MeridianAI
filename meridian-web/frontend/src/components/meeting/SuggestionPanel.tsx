import { useMemo } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { useExitTransition } from '../../hooks/useExitTransition';
import { SuggestionCard } from './SuggestionCard';
import { StructuredSuggestionCard } from './StructuredSuggestionCard';
import { buildTypeStyles } from './suggestionStyles';
import { useNow } from './useNow';
import styles from './SuggestionPanel.module.css';

const formatUpdated = (ts: number | null, now: number): string => {
  if (!ts) return '';
  const sec = Math.max(0, Math.floor((now - ts) / 1000));
  if (sec < 60) return `обновлено ${sec}с назад`;
  return `обновлено ${Math.floor(sec / 60)}м назад`;
};

export const SuggestionPanel: FC = () => {
  const suggestions = useMeetingStore((s) => s.suggestions);
  const streamingText = useMeetingStore((s) => s.currentStreamingText);
  const lastSuggestionTime = useMeetingStore((s) => s.lastSuggestionTime);
  const analysisStatus = useMeetingStore((s) => s.analysisStatus);
  const suggestionLoading = useMeetingStore((s) => s.suggestionLoading);
  const strengthenLoading = useMeetingStore((s) => s.strengthenLoading);
  const customSuggestionTypes = useMeetingStore((s) => s.customSuggestionTypes);
  const typeStyles = useMemo(() => buildTypeStyles(customSuggestionTypes), [customSuggestionTypes]);

  const isAnalyzing = analysisStatus != null || streamingText !== null || suggestionLoading || strengthenLoading;
  const now = useNow(5000);
  const relTime = formatUpdated(lastSuggestionTime, now);

  const statusText = analysisStatus
    || (streamingText !== null ? 'Генерирую подсказку...'
    : suggestionLoading ? 'Формирую AI Подсказки...'
    : strengthenLoading ? 'Анализирую позицию и аргументы...'
    : null);

  // panel-reveal (transitions.dev 07): анализ-бар плавно въезжает/уезжает.
  const analysis = useExitTransition(isAnalyzing && statusText != null, {
    closeVar: '--panel-close-dur',
    fallbackMs: 350,
  });

  return (
    <div className={`suggestion-panel ${styles.container}`}>
      {/* Header */}
      <div className={styles.header}>
        <span className={`${styles.dot} ${isAnalyzing ? styles.dotBusy : ''}`} />
        <span className={styles.title}>AI Подсказки</span>
        {suggestions.length > 0 && (
          <span className={styles.meta}>
            {suggestions.length} актуальных{relTime ? ` · ${relTime}` : ''}
          </span>
        )}
      </div>

      {/* Analysis status bar */}
      {analysis.mounted && (
        <div
          className={`t-panel-slide ${styles.analysisBar}`}
          data-open={analysis.open ? 'true' : 'false'}
        >
          <span className={styles.analysisDots}>•••</span> {statusText}
        </div>
      )}

      {/* Cards */}
      <div className={styles.cards}>
        {suggestions.length === 0 && !isAnalyzing && (
          <div className={styles.placeholder}>
            Здесь появятся AI Подсказки.
            Начните прослушивание переговоров или запросите подсказку вручную.
          </div>
        )}

        {/* Streaming card (for backward compat with streaming suggestions) */}
        {streamingText !== null && (
          <div className={`${styles.card} ${styles.cardStreaming}`}>
            <span className={`${styles.badge} ${styles.badgeStrong}`}>
              Генерация...
            </span>
            <div className={styles.cardText}>{streamingText}</div>
          </div>
        )}

        {/* Suggestion cards (newest first) */}
        {[...suggestions].reverse().map((s, i) => (
          s.card
            ? <StructuredSuggestionCard key={i} card={s.card} />
            : <SuggestionCard key={i} suggestion={s} typeStyles={typeStyles} now={now} />
        ))}
      </div>
    </div>
  );
};
