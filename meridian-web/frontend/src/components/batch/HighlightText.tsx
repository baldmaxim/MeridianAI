import type { FC, ReactNode } from 'react';
import styles from './HighlightText.module.css';

interface IHighlightTextProps {
  text: string;
  /** Запрос в нижнем регистре. */
  query: string;
}

/** Подсветка совпадений запроса в тексте реплики. */
export const HighlightText: FC<IHighlightTextProps> = ({ text, query }) => {
  if (!query) return <>{text}</>;
  const lower = text.toLowerCase();
  const parts: ReactNode[] = [];
  let i = 0;
  let idx = lower.indexOf(query, i);
  let k = 0;
  while (idx >= 0) {
    if (idx > i) parts.push(text.slice(i, idx));
    parts.push(
      <mark key={k++} className={styles.mark}>
        {text.slice(idx, idx + query.length)}
      </mark>
    );
    i = idx + query.length;
    idx = lower.indexOf(query, i);
  }
  if (i < text.length) parts.push(text.slice(i));
  return <>{parts}</>;
};
