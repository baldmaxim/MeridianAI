import { useState } from 'react';
import type { FC } from 'react';
import styles from './ClampedText.module.css';

interface IClampedTextProps {
  label: string;
  text: string;
}

/** Длиннее — обрезаем до двух строк с раскрытием «ещё». */
const CLAMP_MIN_LENGTH = 120;

/** Подписанный текст в две строки; длинный раскрывается кнопкой «ещё». */
export const ClampedText: FC<IClampedTextProps> = ({ label, text }) => {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > CLAMP_MIN_LENGTH || text.split('\n').length > 2;
  return (
    <div className={styles.row}>
      <span className={styles.label}>{label}</span>
      <div className={styles.body}>
        <span className={long && !expanded ? styles.clamped : styles.full}>{text}</span>
        {long && (
          <button type="button" className={styles.more} aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
            {expanded ? 'свернуть' : 'ещё'}
          </button>
        )}
      </div>
    </div>
  );
};
