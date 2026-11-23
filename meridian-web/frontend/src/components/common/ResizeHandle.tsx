import { useRef, useState } from 'react';
import type { FC, KeyboardEvent, PointerEvent } from 'react';
import type { IResizableWidth } from '../../hooks/useResizableWidth';
import styles from './ResizeHandle.module.css';

const KEY_STEP_PX = 16;

interface IResizeHandleProps {
  resizable: IResizableWidth;
  /** Доп. класс: например, скрытие на узких экранах. */
  className?: string;
  label?: string;
}

/** Хендл для растягивания панели: мышь/палец, двойной клик — сброс, стрелки — шаг 16px. */
export const ResizeHandle: FC<IResizeHandleProps> = ({
  resizable, className = '', label = 'Изменить ширину панели',
}) => {
  const { width, min, max, side, setWidth, reset } = resizable;
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ x: number; width: number } | null>(null);
  const last = useRef(width);

  // Хендл у левого края: тянем влево — панель шире; у правого — наоборот.
  const sign = side === 'left' ? -1 : 1;

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    start.current = { x: e.clientX, width };
    last.current = width;
    setDragging(true);
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const s = start.current;
    if (!s) return;
    const next = s.width + sign * (e.clientX - s.x);
    last.current = next;
    setWidth(next, false);
  };

  const finish = (e: PointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    start.current = null;
    setDragging(false);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    setWidth(last.current, true);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const dir = e.key === 'ArrowRight' ? 1 : -1;
    setWidth(width + sign * dir * KEY_STEP_PX);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      className={`${styles.handle} ${side === 'left' ? styles.left : styles.right} ${dragging ? styles.dragging : ''} ${className}`.trim()}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onDoubleClick={reset}
      onKeyDown={onKeyDown}
    />
  );
};
