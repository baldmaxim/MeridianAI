import type { FC, ReactNode } from 'react';
import type { BatchCorrection } from '../../api/batch';
import { HighlightText } from './HighlightText';
import styles from './CorrectedText.module.css';

interface ICorrectedTextProps {
  text: string;
  corrections?: BatchCorrection[];
  /** true — вместо исправленных слов показать распознанные. */
  showOriginal: boolean;
  /** Запрос поиска в нижнем регистре. */
  query: string;
}

/** Текст реплики с пометкой «✎» у слов, исправленных по словарю. */
export const CorrectedText: FC<ICorrectedTextProps> = ({ text, corrections, showOriginal, query }) => {
  if (!corrections?.length) return <HighlightText text={text} query={query} />;

  // Правки идут в порядке слов: ищем «to» с места, где закончилась предыдущая.
  const parts: ReactNode[] = [];
  let pos = 0;
  corrections.forEach((c, k) => {
    const idx = text.indexOf(c.to, pos);
    if (idx < 0) return;
    if (idx > pos) parts.push(<HighlightText key={`t${k}`} text={text.slice(pos, idx)} query={query} />);
    parts.push(
      showOriginal ? (
        <HighlightText key={`c${k}`} text={c.from} query={query} />
      ) : (
        <span key={`c${k}`} className={styles.fixed} title={`Распознано: ${c.from}`}>
          <HighlightText text={c.to} query={query} />
          <span className={styles.mark} aria-label={`Исправлено, распознано: ${c.from}`}>✎</span>
        </span>
      )
    );
    pos = idx + c.to.length;
  });
  if (pos < text.length) parts.push(<HighlightText key="tail" text={text.slice(pos)} query={query} />);
  return <>{parts}</>;
};
