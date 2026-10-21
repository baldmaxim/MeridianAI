import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

const KEY = 'meridian-theme';

/** jsdom не реализует matchMedia — подменяем до первого импорта модуля (он читает его на верхнем уровне). */
const mockMatchMedia = (dark: boolean) => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches: dark,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
};

const loadHook = async (saved?: string, systemDark = false) => {
  vi.resetModules();
  localStorage.clear();
  if (saved) localStorage.setItem(KEY, saved);
  mockMatchMedia(systemDark);
  document.head.innerHTML = '<meta name="theme-color" content="#000000">';
  const { useTheme } = await import('./useTheme');
  return renderHook(() => useTheme());
};

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useTheme', () => {
  it('по умолчанию — системная тема', async () => {
    const { result } = await loadHook(undefined, true);
    expect(result.current.mode).toBe('system');
    expect(result.current.resolved).toBe('dark');
  });

  it('читает сохранённый режим из localStorage', async () => {
    const { result } = await loadHook('light', true);
    expect(result.current.mode).toBe('light');
    expect(result.current.resolved).toBe('light');
  });

  it('игнорирует мусор в localStorage', async () => {
    const { result } = await loadHook('purple');
    expect(result.current.mode).toBe('system');
  });

  it('cycleMode: system → light → dark → system', async () => {
    const { result } = await loadHook();
    const seen: string[] = [result.current.mode];
    for (let i = 0; i < 3; i++) {
      act(() => result.current.cycleMode());
      seen.push(result.current.mode);
    }
    expect(seen).toEqual(['system', 'light', 'dark', 'system']);
  });

  it('setMode сохраняет режим, ставит data-theme и theme-color', async () => {
    const { result } = await loadHook();
    act(() => result.current.setMode('dark'));
    expect(localStorage.getItem(KEY)).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe('#080A0F');

    act(() => result.current.setMode('light'));
    expect(localStorage.getItem(KEY)).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe('#F3F5F9');
  });

  it('режим system следует за темой ОС', async () => {
    const { result } = await loadHook(undefined, false);
    act(() => result.current.setMode('system'));
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });
});
