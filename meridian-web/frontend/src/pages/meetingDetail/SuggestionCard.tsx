import type { FC } from 'react';
import type { MeetingSuggestionRecord } from '../../types';
import { formatTime, getSuggestionTypeInfo } from './meetingDetailFormat';
import styles from './SuggestionCards.module.css';

interface ISuggestionCardProps {
  suggestion: MeetingSuggestionRecord;
}

export const SuggestionCard: FC<ISuggestionCardProps> = ({ suggestion }) => {
  const typeInfo = suggestion.suggestion_type ? getSuggestionTypeInfo(suggestion.suggestion_type) : null;

  return (
    <div className={styles.card}>
      <div className={styles.top}>
        {typeInfo && (
          <span className={`${styles.typeBadge} ${styles[typeInfo.tone]}`}>
            {typeInfo.label}
          </span>
        )}
        {suggestion.is_auto && <span className={styles.autoBadge}>АВТО</span>}
        <span className={styles.time}>{formatTime(suggestion.created_at)}</span>
      </div>
      <div className={styles.text}>{suggestion.text}</div>
      {(suggestion.trigger || suggestion.context_info) && (
        <div className={styles.meta}>
          {suggestion.trigger && <span>Триггер: {suggestion.trigger}</span>}
          {suggestion.context_info && <span>{suggestion.context_info}</span>}
        </div>
      )}
    </div>
  );
};
