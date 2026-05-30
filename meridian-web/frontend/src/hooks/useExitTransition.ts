/* eslint-disable react-hooks/set-state-in-effect --
   transition-примитив: setState в эффекте синхронизирует
   mount/unmount с CSS-таймингом (внешняя система — DOM-анимация). */
import { useEffect, useRef, useState } from 'react';

/**
 * useExitTransition — отложенный размонтаж для transitions.dev панелей,
 * управляемых через data-open (panel-reveal, modal, dropdown).
 *
 * React по умолчанию размонтирует элемент мгновенно при смене состояния,
 * убивая exit-анимацию. Хук держит элемент смонтированным на время
 * close-анимации, а на входе сначала рендерит закрытое состояние и на
 * следующем кадре открывает (чтобы CSS-переход запустился).
 *
 *   const p = useExitTransition(isOpen, { closeVar: '--panel-close-dur' });
 *   {p.mounted && <div className="t-panel-slide" data-open={p.open}>…</div>}
 *
 * StrictMode/unmount-safe: таймер и rAF в ref, очищаются в cleanup.
 * Reduced-motion → мгновенный размонтаж без задержки.
 */
interface Options {
  /** CSS-переменная с длительностью закрытия (мс/с). */
  closeVar?: string;
  /** Фолбэк, если переменную не прочитать. */
  fallbackMs?: number;
}

export function useExitTransition(open: boolean, opts: Options = {}) {
  const { closeVar = '--panel-close-dur', fallbackMs = 300 } = opts;
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(open);
  const firstRun = useRef(true);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const raf1 = useRef<number | null>(null);
  const raf2 = useRef<number | null>(null);

  const cancelRaf = () => {
    if (raf1.current) cancelAnimationFrame(raf1.current);
    if (raf2.current) cancelAnimationFrame(raf2.current);
    raf1.current = null;
    raf2.current = null;
  };

  useEffect(() => {
    // Первый прогон: инициализация без анимации (уже открытое не «въезжает»).
    if (firstRun.current) {
      firstRun.current = false;
      setMounted(open);
      setShown(open);
      return;
    }

    if (open) {
      if (closeTimer.current) {
        clearTimeout(closeTimer.current);
        closeTimer.current = null;
      }
      setMounted(true);
      setShown(false); // стартуем из закрытого состояния…
      cancelRaf();
      raf1.current = requestAnimationFrame(() => {
        raf2.current = requestAnimationFrame(() => setShown(true)); // …и открываем на след. кадре
      });
    } else {
      cancelRaf();
      setShown(false);
      const reduce =
        typeof window !== 'undefined' &&
        window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      if (reduce) {
        setMounted(false);
        return;
      }
      const dur =
        parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue(closeVar)
        ) || fallbackMs;
      if (closeTimer.current) clearTimeout(closeTimer.current);
      closeTimer.current = setTimeout(() => {
        setMounted(false);
        closeTimer.current = null;
      }, dur);
    }
  }, [open, closeVar, fallbackMs]);

  useEffect(
    () => () => {
      if (closeTimer.current) clearTimeout(closeTimer.current);
      cancelRaf();
    },
    []
  );

  return { mounted, open: shown };
}
