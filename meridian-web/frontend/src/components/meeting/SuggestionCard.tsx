import type { FC } from 'react';
import type { Suggestion } from '../../types';
import { SuggestionConfidenceBar } from './SuggestionConfidenceBar';
import { colorVar, getTypeStyle } from './suggestionStyles';
import type { ISuggestionTypeStyle } from './suggestionStyles';
import styles from './SuggestionPanel.module.css';

interface ISuggestionCardProps {
  suggestion: Suggestion;
  typeStyles: Record<string, ISuggestionTypeStyle>;
  /** Текущее время (мс) для подписи «N с назад» */
  now: number;
}

const formatRelative = (date: Date, now: number): string => {
  const sec = Math.max(0, Math.floor((now - date.getTime()) / 1000));
  if (sec < 60) return `${sec}с назад`;
  return `${Math.floor(sec / 60)}м назад`;
};

export const SuggestionCard: FC<ISuggestionCardProps> = ({ suggestion, typeStyles, now }) => {
  const ts = getTypeStyle(suggestion, typeStyles);
  const meta = suggestion.trigger || suggestion.context_info;
  const isPriority = suggestion.type === 'priority' && suggestion.confidence != null;
  const filledBars = isPriority ? Math.ceil((suggestion.confidence! / 100) * 4) : 0;

  return (
    <div className={styles.card} style={colorVar(ts.color)}>
      {/* Top: badge + confidence/time */}
      <div className={styles.cardTop}>
        <span className={styles.badge}>{ts.badge}</span>
        {isPriority ? (
          <div className={styles.confidenceCompact}>
            <span className={styles.confidenceBars}>
              {[...Array(4)].map((_, i) => (
                <span key={i} className={`${styles.confidenceBarItem} ${i < filledBars ? styles.confidenceBarOn : ''}`} />
              ))}
            </span>
            <span className={styles.confidencePct}>{suggestion.confidence}%</span>
          </div>
        ) : (
          <span className={styles.cardTime}>{formatRelative(suggestion.timestamp, now)}</span>
        )}
      </div>

      {/* Confidence bar for priority */}
      {isPriority && <SuggestionConfidenceBar value={suggestion.confidence!} />}

      {/* Main text */}
      <div className={styles.cardText}>{suggestion.text}</div>

      {/* Meta info: trigger / context / method / pattern */}
      {meta && (
        <div className={styles.metaLine}>
          — {ts.metaLabel}: <span className={styles.metaValue}>
            {suggestion.trigger
              ? suggestion.trigger.split(',').map(t => `«${t.trim()}»`).join(', ')
              : suggestion.context_info}
          </span>
        </div>
      )}

      {/* Actions */}
      <div className={styles.cardActions}>
        <button className={styles.actionBtn}>
          {ts.actionLabel}
        </button>
        {ts.secondaryAction && (
          <button className={styles.actionBtnSecondary}>
            {ts.secondaryAction}
          </button>
        )}
      </div>
    </div>
  );
};
