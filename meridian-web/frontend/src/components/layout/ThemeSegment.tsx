import type { FC } from 'react';
import { useTheme, type ThemeMode } from '../../hooks/useTheme';
import styles from './ThemeSegment.module.css';

const MODES: { mode: ThemeMode; label: string }[] = [
  { mode: 'system', label: 'Система' },
  { mode: 'light', label: 'Светлая' },
  { mode: 'dark', label: 'Тёмная' },
];

/** Сегмент выбора темы из трёх кнопок: Система / Светлая / Тёмная. */
export const ThemeSegment: FC = () => {
  const { mode, setMode } = useTheme();
  return (
    <div className={styles.segment} role="radiogroup" aria-label="Тема оформления">
      {MODES.map((m) => (
        <button
          key={m.mode}
          type="button"
          role="radio"
          aria-checked={mode === m.mode}
          className={`${styles.option} ${mode === m.mode ? styles.optionActive : ''}`}
          onClick={() => setMode(m.mode)}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
};
