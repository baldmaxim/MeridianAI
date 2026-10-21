import type { FC } from 'react';
import styles from './SuggestionPanel.module.css';

interface ISuggestionConfidenceBarProps {
  /** 0..100; цвет берётся из CSS-переменной --c карточки */
  value: number;
}

export const SuggestionConfidenceBar: FC<ISuggestionConfidenceBarProps> = ({ value }) => (
  <div className={styles.confidenceRow}>
    <span className={styles.confidenceLabel}>УВЕРЕННОСТЬ</span>
    <div className={styles.confidenceTrack}>
      <div
        className={styles.confidenceFill}
        style={{ transform: `scaleX(${Math.min(100, Math.max(0, value)) / 100})` }}
      />
    </div>
    <span className={styles.confidenceValue}>{value}</span>
  </div>
);
