import type { FC } from 'react';
import styles from './MultiChannelReconciliationPanel.module.css';
import tone from './Tone.module.css';

interface IReconciliationChipProps {
  label: string;
  value: number;
  /** Класс цвета значения (из Tone.module.css); по умолчанию — основной текст */
  toneClass?: string;
}

export const ReconciliationChip: FC<IReconciliationChipProps> = ({ label, value, toneClass = tone.primary }) => (
  <span className={styles.chip}>
    <span className={styles.chipLabel}>{label}</span>
    <span className={`${styles.chipVal} ${toneClass}`}>{value}</span>
  </span>
);
