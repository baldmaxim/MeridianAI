/* eslint-disable react-hooks/set-state-in-effect --
   transition-примитив: setState в эффекте синхронизирует
   mount/unmount с CSS-таймингом (внешняя система — DOM-анимация). */
import { useEffect, useRef, useState } from 'react';

/**
 * useOpenClose — оркестрация .is-open / .is-closing для transitions.dev
 * surfaces, растущих из rest-состояния (modal 06, dropdown 05).
 *
 * Отличается от useExitTransition (тот для data-open панелей): здесь элемент
 * на входе сначала рендерится в rest-состоянии (scale < 1, opacity 0), а на
 * следующем кадре получает .is-open → CSS-переход проигрывается. На закрытии
 * вешается .is-closing и через --*-close-dur мс элемент размонтируется.
 *
 *   const m = useOpenClose(open, { closeVar: '--modal-close-dur' });
 *   {m.mounted && <div className={`t-modal ${m.cls}`}>…</div>}
 *
 * StrictMode/unmount-safe: таймеры и rAF в ref, очищаются в cleanup.
 * Reduced-motion → мгновенный mount/unmount без задержки.
 */
interface Options {
  /** CSS-переменная с длительностью закрытия (мс/с). */
  closeVar?: string;
  /** Фолбэк, если переменную не прочитать. */
  fallbackMs?: number;
}

export function useOpenClose(open: boolean, opts: Options = {}) {
  const { closeVar = '--modal-close-dur', fallbackMs = 150 } = opts;
  const [mounted, setMounted] = useState(open);
  const [cls, setCls] = useState<'' | 'is-open' | 'is-closing'>(
    open ? 'is-open' : ''
  );
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
    if (firstRun.current) {
      firstRun.current = false;
      setMounted(open);
      setCls(open ? 'is-open' : '');
      return;
    }

    if (open) {
      if (closeTimer.current) {
        clearTimeout(closeTimer.current);
        closeTimer.current = null;
      }
      setMounted(true);
      setCls(''); // стартуем из rest-состояния…
      cancelRaf();
      raf1.current = requestAnimationFrame(() => {
        raf2.current = requestAnimationFrame(() => setCls('is-open')); // …открываем на след. кадре
      });
    } else {
      cancelRaf();
      const reduce =
        typeof window !== 'undefined' &&
        window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      if (reduce) {
        setCls('');
        setMounted(false);
        return;
      }
      setCls('is-closing');
      const dur =
        parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue(closeVar)
        ) || fallbackMs;
      if (closeTimer.current) clearTimeout(closeTimer.current);
      closeTimer.current = setTimeout(() => {
        setMounted(false);
        setCls('');
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

  return { mounted, cls };
}
