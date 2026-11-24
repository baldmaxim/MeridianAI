import { useRef } from 'react';
import type { PointerEvent } from 'react';

export type TSwipeDirection = 'left' | 'right';

/** Порог по X, px. */
export const SWIPE_THRESHOLD = 50;

/** Свайп засчитывается, если сдвиг по X ≥ порога и горизонтальный сдвиг больше вертикального. */
export const swipeDirection = (dx: number, dy: number, threshold = SWIPE_THRESHOLD): TSwipeDirection | null => {
  if (Math.abs(dx) < threshold || Math.abs(dx) <= Math.abs(dy)) return null;
  return dx < 0 ? 'left' : 'right';
};

interface IStart {
  id: number;
  x: number;
  y: number;
}

/**
 * Свайп влево/вправо на тач-устройствах (pointer events). Мышь не трогаем — иначе выделение текста
 * переключало бы вкладку. Вертикальную прокрутку отдаём браузеру (touch-action: pan-y на элементе):
 * он присылает pointercancel, и состояние сбрасывается. Начало на таблице игнорируем — у неё своя горизонтальная прокрутка.
 */
export const useHorizontalSwipe = (onSwipe: (direction: TSwipeDirection) => void) => {
  const start = useRef<IStart | null>(null);

  const onPointerDown = (e: PointerEvent<HTMLElement>) => {
    const touchLike = e.pointerType === 'touch' || e.pointerType === 'pen';
    const onTable = e.target instanceof Element && e.target.closest('table') !== null;
    start.current = touchLike && !onTable ? { id: e.pointerId, x: e.clientX, y: e.clientY } : null;
  };

  const onPointerUp = (e: PointerEvent<HTMLElement>) => {
    const s = start.current;
    start.current = null;
    if (!s || s.id !== e.pointerId) return;
    const dir = swipeDirection(e.clientX - s.x, e.clientY - s.y);
    if (dir) onSwipe(dir);
  };

  const onPointerCancel = () => { start.current = null; };

  return { onPointerDown, onPointerUp, onPointerCancel };
};
