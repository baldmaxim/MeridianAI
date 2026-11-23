import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export type TResizeSide = 'left' | 'right';

export interface IUseResizableWidthOptions {
  /** Ключ localStorage, в котором хранится ширина. */
  storageKey: string;
  min: number;
  /** Верхняя граница; функция — для границы от размера окна (пересчитывается при resize). */
  max: number | (() => number);
  defaultWidth: number;
  /** С какой стороны панели стоит хендл: у левого края тянут влево — панель шире. */
  side: TResizeSide;
}

export interface IResizableWidth {
  width: number;
  min: number;
  max: number;
  side: TResizeSide;
  defaultWidth: number;
  /** persist=false — промежуточное значение при перетаскивании (без записи в localStorage). */
  setWidth: (next: number, persist?: boolean) => void;
  reset: () => void;
}

export const clampWidth = (value: number, min: number, max: number): number =>
  Math.round(Math.min(Math.max(value, min), Math.max(min, max)));

/** Сохранённая ширина или null, если значения нет / оно не число. */
export const readStoredWidth = (storageKey: string): number | null => {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
};

const writeStoredWidth = (storageKey: string, value: number | null) => {
  try {
    if (value == null) window.localStorage.removeItem(storageKey);
    else window.localStorage.setItem(storageKey, String(value));
  } catch {
    /* localStorage недоступен (приватный режим) — ширина живёт до перезагрузки */
  }
};

/** Ширина панели, которую пользователь тянет мышью/пальцем; запоминается в localStorage. */
export const useResizableWidth = ({
  storageKey, min, max, defaultWidth, side,
}: IUseResizableWidthOptions): IResizableWidth => {
  const maxRef = useRef(max);
  useEffect(() => { maxRef.current = max; });

  const resolveMax = useCallback((): number => {
    const m = maxRef.current;
    return typeof m === 'function' ? m() : m;
  }, []);

  const [maxPx, setMaxPx] = useState<number>(() => (typeof max === 'function' ? max() : max));
  const [raw, setRaw] = useState<number>(() => readStoredWidth(storageKey) ?? defaultWidth);

  useEffect(() => {
    const onResize = () => setMaxPx(resolveMax());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [resolveMax]);

  const width = useMemo(() => clampWidth(raw, min, maxPx), [raw, min, maxPx]);

  const setWidth = useCallback((next: number, persist = true) => {
    const value = clampWidth(next, min, resolveMax());
    setRaw(value);
    if (persist) writeStoredWidth(storageKey, value);
  }, [min, resolveMax, storageKey]);

  const reset = useCallback(() => {
    setRaw(defaultWidth);
    writeStoredWidth(storageKey, null);
  }, [defaultWidth, storageKey]);

  return { width, min, max: Math.max(min, maxPx), side, defaultWidth, setWidth, reset };
};
