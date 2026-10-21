import type { FC, ReactNode } from 'react';
import { useTheme, type ThemeMode } from '../../hooks/useTheme';
import styles from './ThemeToggle.module.css';

const ICON_PROPS = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
} as const;

const ICONS: Record<ThemeMode, ReactNode> = {
  system: (
    <svg {...ICON_PROPS}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  ),
  light: (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  ),
  dark: (
    <svg {...ICON_PROPS}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  ),
};

const LABELS: Record<ThemeMode, string> = {
  system: 'Системная',
  light: 'Светлая',
  dark: 'Тёмная',
};

const NEXT_LABEL: Record<ThemeMode, string> = {
  system: LABELS.light,
  light: LABELS.dark,
  dark: LABELS.system,
};

/** Одна кнопка: Системная → Светлая → Тёмная. Тап-цель 44×44. */
export const ThemeToggle: FC = () => {
  const { mode, cycleMode } = useTheme();
  const title = `Тема: ${LABELS[mode]}. Нажмите — ${NEXT_LABEL[mode]}`;
  return (
    <button
      type="button"
      className={`theme-toggle t-btn ${styles.btn}`}
      onClick={cycleMode}
      aria-label={title}
      title={title}
    >
      {ICONS[mode]}
      <span className={styles.label}>Тема: {LABELS[mode]}</span>
    </button>
  );
};
