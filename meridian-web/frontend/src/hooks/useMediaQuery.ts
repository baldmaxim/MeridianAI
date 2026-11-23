import { useSyncExternalStore } from 'react';

const subscribeTo = (query: string) => (onChange: () => void) => {
  const mql = window.matchMedia(query);
  mql.addEventListener('change', onChange);
  return () => mql.removeEventListener('change', onChange);
};

/** Совпадает ли медиа-запрос прямо сейчас (обновляется при изменении размера окна). */
export const useMediaQuery = (query: string): boolean =>
  useSyncExternalStore(
    (cb) => (typeof window.matchMedia === 'function' ? subscribeTo(query)(cb) : () => {}),
    () => (typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : false),
    () => false,
  );
