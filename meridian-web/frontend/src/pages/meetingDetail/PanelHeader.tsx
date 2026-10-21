import type { FC } from 'react';
import styles from './PanelHeader.module.css';

interface IPanelHeaderProps {
  title: string;
  /** Правая подпись (счётчик). */
  meta?: string | number;
  /** Цвет точки слева. */
  accent?: 'amber' | 'green';
  /** Без рамки и отступов — шапка внутри уже обрамлённого блока. */
  plain?: boolean;
}

export const PanelHeader: FC<IPanelHeaderProps> = ({ title, meta, accent = 'amber', plain = false }) => (
  <div className={`${styles.header}${plain ? ` ${styles.plain}` : ''}`}>
    <span className={`${styles.dot}${accent === 'green' ? ` ${styles.dotGreen}` : ''}`} />
    <span className={styles.title}>{title}</span>
    {meta !== undefined && <span className={styles.meta}>{meta}</span>}
  </div>
);
