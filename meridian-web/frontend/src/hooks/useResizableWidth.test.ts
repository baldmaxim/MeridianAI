import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { clampWidth, readStoredWidth, useResizableWidth } from './useResizableWidth';

const KEY = 'test-panel-width';
const opts = { storageKey: KEY, min: 240, max: 600, defaultWidth: 260, side: 'left' as const };

beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

describe('clampWidth', () => {
  it('ограничивает диапазоном и округляет', () => {
    expect(clampWidth(100, 240, 600)).toBe(240);
    expect(clampWidth(900, 240, 600)).toBe(600);
    expect(clampWidth(300.6, 240, 600)).toBe(301);
  });

  it('max меньше min — берётся min', () => {
    expect(clampWidth(500, 240, 100)).toBe(240);
  });
});

describe('readStoredWidth', () => {
  it('нет значения или мусор — null', () => {
    expect(readStoredWidth(KEY)).toBeNull();
    window.localStorage.setItem(KEY, 'abc');
    expect(readStoredWidth(KEY)).toBeNull();
  });
});

describe('useResizableWidth', () => {
  it('по умолчанию — defaultWidth', () => {
    const { result } = renderHook(() => useResizableWidth(opts));
    expect(result.current.width).toBe(260);
  });

  it('читает сохранённую ширину и ограничивает её диапазоном', () => {
    window.localStorage.setItem(KEY, '400');
    expect(renderHook(() => useResizableWidth(opts)).result.current.width).toBe(400);
    window.localStorage.setItem(KEY, '9999');
    expect(renderHook(() => useResizableWidth(opts)).result.current.width).toBe(600);
  });

  it('setWidth ограничивает и пишет в localStorage; persist=false — не пишет', () => {
    const { result } = renderHook(() => useResizableWidth(opts));
    act(() => result.current.setWidth(1000));
    expect(result.current.width).toBe(600);
    expect(window.localStorage.getItem(KEY)).toBe('600');
    act(() => result.current.setWidth(10, false));
    expect(result.current.width).toBe(240);
    expect(window.localStorage.getItem(KEY)).toBe('600');
  });

  it('reset возвращает дефолт и чистит localStorage', () => {
    const { result } = renderHook(() => useResizableWidth(opts));
    act(() => result.current.setWidth(500));
    act(() => result.current.reset());
    expect(result.current.width).toBe(260);
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it('max-функция: ширина пересчитывается при resize окна', () => {
    let limit = 600;
    const { result } = renderHook(() => useResizableWidth({ ...opts, max: () => limit }));
    act(() => result.current.setWidth(500));
    limit = 300;
    act(() => { window.dispatchEvent(new Event('resize')); });
    expect(result.current.width).toBe(300);
    expect(result.current.max).toBe(300);
  });
});
