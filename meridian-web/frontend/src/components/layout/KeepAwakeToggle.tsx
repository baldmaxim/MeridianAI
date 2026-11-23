import { useCallback, useEffect, useRef, useState } from 'react';
import type { FC } from 'react';
import { IconSwap } from '../common/IconSwap';
import headerStyles from './Header.module.css';
import styles from './KeepAwakeToggle.module.css';

const STORAGE_KEY = 'meridian_keep_awake';

const isSupported = (): boolean => typeof navigator !== 'undefined' && 'wakeLock' in navigator;

const readEnabled = (): boolean => {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
};

const writeEnabled = (value: boolean): void => {
  try {
    localStorage.setItem(STORAGE_KEY, value ? '1' : '0');
  } catch {
    /* localStorage недоступен — выбор живёт до перезагрузки */
  }
};

/** Лампочка: контур (выкл) и с заливкой (вкл). stroke/fill — currentColor, цвет задаёт состояние кнопки. */
const BulbIcon: FC<{ on: boolean }> = ({ on }) => (
  <svg
    width={20}
    height={20}
    viewBox="0 0 24 24"
    fill={on ? 'currentColor' : 'none'}
    fillOpacity={on ? 0.25 : undefined}
    stroke="currentColor"
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z" />
    <path d="M9.5 18.5h5M10.5 21h3" fill="none" />
  </svg>
);

/**
 * Кнопка «Не гасить экран» (Screen Wake Lock). Независима от useWakeLock записи встречи:
 * свой sentinel, поэтому остановка встречи не снимает ручной lock и наоборот.
 * Состояния: выкл / вкл и удерживается / вкл, но запрос не удался (iOS часто требует жест).
 * Пока запрос в полёте, кнопка выглядит как «удерживается».
 */
export const KeepAwakeToggle: FC = () => {
  const [enabled, setEnabled] = useState<boolean>(readEnabled);
  const [held, setHeld] = useState(false);
  const [failed, setFailed] = useState(false);

  const enabledRef = useRef(enabled);
  const mountedRef = useRef(false);
  const sentinelRef = useRef<WakeLockSentinel | null>(null);
  const pendingRef = useRef(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const gestureHandlerRef = useRef<((e: PointerEvent) => void) | null>(null);

  const disarmGesture = useCallback(() => {
    if (gestureHandlerRef.current) {
      document.removeEventListener('pointerdown', gestureHandlerRef.current);
      gestureHandlerRef.current = null;
    }
  }, []);

  const releaseSentinel = useCallback(() => {
    const s = sentinelRef.current;
    sentinelRef.current = null;
    if (s) {
      try { void s.release(); } catch { /* ignore */ }
    }
  }, []);

  // Запрос lock. Флаг pendingRef не даёт visibilitychange+pageshow создать два sentinel.
  const acquire = useCallback(async (): Promise<void> => {
    if (!isSupported() || !enabledRef.current || sentinelRef.current || pendingRef.current) return;
    pendingRef.current = true;
    try {
      const s = await navigator.wakeLock.request('screen');
      // За время запроса кнопку выключили или размонтировали — сразу отпускаем
      if (!enabledRef.current || !mountedRef.current) {
        try { void s.release(); } catch { /* ignore */ }
        return;
      }
      sentinelRef.current = s;
      s.addEventListener('release', () => {
        if (sentinelRef.current === s) {
          sentinelRef.current = null;
          setHeld(false);
        }
      }, { once: true });
      setHeld(true);
      setFailed(false);
    } catch {
      setHeld(false);
      setFailed(true);
      // Без жеста iOS отказывает — повторим на ближайшем касании вне кнопки (касание кнопки обрабатывает её onClick)
      if (!gestureHandlerRef.current) {
        const onGesture = (e: PointerEvent) => {
          if (btnRef.current?.contains(e.target as Node)) return;
          disarmGesture();
          void acquire();
        };
        gestureHandlerRef.current = onGesture;
        document.addEventListener('pointerdown', onGesture, { once: true });
      }
    } finally {
      pendingRef.current = false;
    }
  }, [disarmGesture]);

  useEffect(() => {
    if (!isSupported()) return;
    mountedRef.current = true;
    if (enabledRef.current) void acquire();

    const reacquire = () => {
      if (document.visibilityState === 'visible' && enabledRef.current && !sentinelRef.current) void acquire();
    };
    document.addEventListener('visibilitychange', reacquire);
    window.addEventListener('pageshow', reacquire);
    return () => {
      mountedRef.current = false;
      document.removeEventListener('visibilitychange', reacquire);
      window.removeEventListener('pageshow', reacquire);
      disarmGesture();
      releaseSentinel();
    };
  }, [acquire, disarmGesture, releaseSentinel]);

  const handleClick = () => {
    // Вкл, но не удержан (запрос упал): нажатие — повторная попытка, а не выключение
    if (enabledRef.current && !sentinelRef.current && !pendingRef.current) {
      disarmGesture();
      void acquire();
      return;
    }
    const next = !enabledRef.current;
    enabledRef.current = next;
    setEnabled(next);
    writeEnabled(next);
    if (next) {
      void acquire();
    } else {
      disarmGesture();
      releaseSentinel();
      setHeld(false);
      setFailed(false);
    }
  };

  if (!isSupported()) return null;

  const status: 'off' | 'held' | 'failed' = !enabled ? 'off' : failed && !held ? 'failed' : 'held';
  const title =
    status === 'off' ? 'Экран может гаснуть'
      : status === 'held' ? 'Экран не гаснет'
        : 'Не удалось удержать экран — коснитесь ещё раз';

  return (
    <button
      ref={btnRef}
      type="button"
      className={`t-btn ${headerStyles.iconBtn} ${styles.btn} ${status === 'held' ? styles.held : ''} ${status === 'failed' ? styles.failed : ''}`}
      aria-pressed={enabled}
      aria-label={enabled ? 'Разрешить экрану гаснуть' : 'Не гасить экран'}
      title={title}
      onClick={handleClick}
    >
      <IconSwap state={enabled ? 'b' : 'a'} a={<BulbIcon on={false} />} b={<BulbIcon on />} />
    </button>
  );
};
