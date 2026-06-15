import { useState, useEffect } from 'react';

/** Лёгкий path-роутер без зависимостей (для mobile/recorder routes). */
export function navigate(path: string) {
  if (window.location.pathname === path) return;
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function usePathname(): string {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  return path;
}

/** Разбор маршрута приложения по pathname. */
export type AppRoute =
  | { kind: 'recorder'; meetingId: number }
  | { kind: 'mobile-list' }
  | { kind: 'mobile-detail'; meetingId: number }
  | { kind: 'desktop' };

export function parseRoute(pathname: string): AppRoute {
  const rec = pathname.match(/^\/recorder\/(\d+)\/?$/);
  if (rec) return { kind: 'recorder', meetingId: Number(rec[1]) };
  const detail = pathname.match(/^\/mobile\/meetings\/(\d+)\/?$/);
  if (detail) return { kind: 'mobile-detail', meetingId: Number(detail[1]) };
  if (/^\/mobile(\/meetings)?\/?$/.test(pathname)) return { kind: 'mobile-list' };
  return { kind: 'desktop' };
}
