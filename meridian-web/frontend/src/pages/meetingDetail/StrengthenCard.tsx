import type { FC } from 'react';
import type { MeetingSuggestionRecord } from '../../types';
import { formatTime } from './meetingDetailFormat';
import styles from './SuggestionCards.module.css';

interface IStrengthenCardProps {
  suggestion: MeetingSuggestionRecord;
}

export const StrengthenCard: FC<IStrengthenCardProps> = ({ suggestion }) => (
  <div className={`${styles.card} ${styles.strengthenCard}`}>
    <div className={styles.top}>
      <span className={`${styles.typeBadge} ${styles.strengthen}`}>УСИЛЕНИЕ</span>
      <span className={styles.time}>{formatTime(suggestion.created_at)}</span>
    </div>
    <div className={`${styles.text} ${styles.preWrap}`}>{suggestion.text}</div>
  </div>
);
