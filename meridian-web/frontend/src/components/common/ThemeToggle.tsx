import type { FC } from 'react';
import { useTheme } from '../../hooks/useTheme';
import { IconSwap } from './IconSwap';
import { Icon } from './Icon';
import styles from './ThemeToggle.module.css';

/**
 * Кнопка темы: переключает фактическую тему на противоположную и сохраняет явный выбор.
 * Иконка — на что переключимся (в тёмной теме солнце, в светлой луна); подпись — то же словами.
 * Выбор «Система» остаётся в ThemeSegment (меню пользователя) — хранилище одно (useTheme).
 */
export const ThemeToggle: FC = () => {
  const { resolved, setMode } = useTheme();
  const label = resolved === 'dark' ? 'Светлая тема' : 'Тёмная тема';
  return (
    <button
      type="button"
      className={`theme-toggle t-btn ${styles.btn}`}
      onClick={() => setMode(resolved === 'dark' ? 'light' : 'dark')}
      aria-label={label}
      title={label}
    >
      <IconSwap state={resolved === 'dark' ? 'a' : 'b'} a={<Icon name="sun" />} b={<Icon name="moon" />} />
    </button>
  );
};
