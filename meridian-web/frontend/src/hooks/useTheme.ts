import { useCallback, useSyncExternalStore } from 'react';

export type ThemeMode = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'meridian-theme';
/** Запасные значения = --bg-secondary (фон шапки) в index.css; должны совпадать с public/theme-init.js */
const THEME_COLORS: Record<ResolvedTheme, string> = { dark: '#0D1018', light: '#FFFFFF' };

const isMode = (v: unknown): v is ThemeMode => v === 'system' || v === 'light' || v === 'dark';

const readMode = (): ThemeMode => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return isMode(saved) ? saved : 'system';
  } catch {
    return 'system';
  }
};

const mql: MediaQueryList | null =
  typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

let currentMode: ThemeMode = typeof window !== 'undefined' ? readMode() : 'system';
const listeners = new Set<() => void>();

const resolve = (mode: ThemeMode): ResolvedTheme => {
  if (mode === 'system') return mql?.matches ? 'dark' : 'light';
  return mode;
};

/** Синхронизирует data-theme на <html> и <meta name="theme-color"> */
const applyTheme = (): void => {
  const resolved = resolve(currentMode);
  document.documentElement.setAttribute('data-theme', resolved);
  // Цвет берём из CSS уже после смены data-theme (фон шапки); константы — если токен не прочитался
  const cssColor = getComputedStyle(document.documentElement).getPropertyValue('--bg-secondary').trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', cssColor || THEME_COLORS[resolved]);
};

const emit = (): void => listeners.forEach((l) => l());

const setModeInternal = (mode: ThemeMode): void => {
  currentMode = mode;
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* localStorage недоступен — тема живёт до перезагрузки */
  }
  applyTheme();
  emit();
};

// Пока режим «системная» — следим за сменой темы ОС.
mql?.addEventListener('change', () => {
  if (currentMode !== 'system') return;
  applyTheme();
  emit();
});

const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

const getMode = (): ThemeMode => currentMode;
const getResolved = (): ResolvedTheme => resolve(currentMode);

/** Порядок переключения: Системная → Светлая → Тёмная → … */
const NEXT_MODE: Record<ThemeMode, ThemeMode> = { system: 'light', light: 'dark', dark: 'system' };

export const useTheme = () => {
  const mode = useSyncExternalStore(subscribe, getMode, getMode);
  const resolved = useSyncExternalStore(subscribe, getResolved, getResolved);
  const setMode = useCallback((m: ThemeMode) => setModeInternal(m), []);
  const cycleMode = useCallback(() => setModeInternal(NEXT_MODE[currentMode]), []);
  return { mode, resolved, setMode, cycleMode };
};
