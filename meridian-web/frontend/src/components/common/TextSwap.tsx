/* eslint-disable react-hooks/set-state-in-effect --
   transition-примитив: setState в эффекте управляет фазами
   blur-свапа текста (внешняя система — DOM-переход). */
import { useEffect, useRef, useState } from 'react';

/**
 * TextSwap — text-states-swap (transitions.dev 04-text-states-swap).
 * Старый текст уходит вверх с блюром, новый входит снизу.
 * Трёхфазная машина состояний на чистом React (без императивного classList,
 * чтобы ре-рендер не стирал классы). StrictMode/unmount-safe: таймер и rAF
 * в ref, очищаются в cleanup. Reduced-motion → мгновенная подмена.
 */
type Phase = 'idle' | 'exit' | 'enter';

interface Props {
  value: string;
  style?: React.CSSProperties;
  className?: string;
}

export function TextSwap({ value, style, className = '' }: Props) {
  const [shown, setShown] = useState(value);
  const [phase, setPhase] = useState<Phase>('idle');
  const lastValue = useRef(value);
  const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const raf1 = useRef<number | null>(null);
  const raf2 = useRef<number | null>(null);

  useEffect(() => {
    if (value === lastValue.current) return;
    lastValue.current = value;

    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduce) {
      setShown(value);
      setPhase('idle');
      return;
    }

    const dur =
      parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue('--text-swap-dur')
      ) || 150;

    setPhase('exit');
    if (exitTimer.current) clearTimeout(exitTimer.current);
    exitTimer.current = setTimeout(() => {
      setShown(value);
      setPhase('enter');
      exitTimer.current = null;
    }, dur);
  }, [value]);

  // После маунта "enter" (текст ниже, transition: none) отпускаем в idle на
  // следующем кадре, чтобы браузер успел отрисовать стартовое положение.
  useEffect(() => {
    if (phase !== 'enter') return;
    raf1.current = requestAnimationFrame(() => {
      raf2.current = requestAnimationFrame(() => setPhase('idle'));
    });
    return () => {
      if (raf1.current) cancelAnimationFrame(raf1.current);
      if (raf2.current) cancelAnimationFrame(raf2.current);
    };
  }, [phase]);

  useEffect(
    () => () => {
      if (exitTimer.current) clearTimeout(exitTimer.current);
      if (raf1.current) cancelAnimationFrame(raf1.current);
      if (raf2.current) cancelAnimationFrame(raf2.current);
    },
    []
  );

  const stateClass =
    phase === 'exit' ? 'is-exit' : phase === 'enter' ? 'is-enter-start' : '';
  return (
    <span className={`t-text-swap ${stateClass} ${className}`.trim()} style={style}>
      {shown}
    </span>
  );
}
