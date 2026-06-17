import { useState, useEffect } from 'react';

/** Лёгкий path-роутер без зависимостей. */
export function navigate(path: string) {
  if (window.location.pathname + window.location.search === path) return;
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

/** Канонические адреса страниц приложения. */
export const paths = {
  login: '/login',
  objects: '/objects',
  objectDetail: (id: number) => `/objects/${id}`,
  meeting: '/meeting',
  history: '/history',
  meetingDetail: (id: number, from?: 'history' | 'object', objectId?: number) =>
    from === 'object' && objectId != null
      ? `/meetings/${id}?from=object&obj=${objectId}`
      : `/meetings/${id}`,
  batch: '/batch',
  directory: '/directory',
  dirObjects: '/directory/objects',
  dirDepartments: '/directory/departments',
  knowledge: '/knowledge',
  aiSettings: '/ai-settings',
  settings: '/settings',
};

/** Разбор маршрута приложения по pathname. */
export type AppRoute =
  | { kind: 'recorder'; meetingId: number }
  | { kind: 'mobile-list' }
  | { kind: 'mobile-detail'; meetingId: number }
  | { kind: 'objects' }
  | { kind: 'object-detail'; objectId: number }
  | { kind: 'meeting' }
  | { kind: 'history' }
  | { kind: 'meeting-detail'; meetingId: number; from: 'history' | 'object'; objectId?: number }
  | { kind: 'batch' }
  | { kind: 'directory' }
  | { kind: 'dir-objects' }
  | { kind: 'dir-departments' }
  | { kind: 'knowledge' }
  | { kind: 'ai-settings' }
  | { kind: 'settings' }
  | { kind: 'login' };

export function parseRoute(pathname: string): AppRoute {
  // Мобильные / recorder маршруты (прямые ссылки, QR).
  const rec = pathname.match(/^\/recorder\/(\d+)\/?$/);
  if (rec) return { kind: 'recorder', meetingId: Number(rec[1]) };
  const mdetail = pathname.match(/^\/mobile\/meetings\/(\d+)\/?$/);
  if (mdetail) return { kind: 'mobile-detail', meetingId: Number(mdetail[1]) };
  if (/^\/mobile(\/meetings)?\/?$/.test(pathname)) return { kind: 'mobile-list' };

  // Десктопные страницы — каждая по своему адресу.
  if (pathname === '/login') return { kind: 'login' };
  if (pathname === '/' || /^\/objects\/?$/.test(pathname)) return { kind: 'objects' };
  const objDetail = pathname.match(/^\/objects\/(\d+)\/?$/);
  if (objDetail) return { kind: 'object-detail', objectId: Number(objDetail[1]) };
  if (/^\/meeting\/?$/.test(pathname)) return { kind: 'meeting' };
  if (/^\/history\/?$/.test(pathname)) return { kind: 'history' };
  const meetDetail = pathname.match(/^\/meetings\/(\d+)\/?$/);
  if (meetDetail) {
    const q = new URLSearchParams(window.location.search);
    const from = q.get('from') === 'object' ? 'object' : 'history';
    const obj = q.get('obj');
    return { kind: 'meeting-detail', meetingId: Number(meetDetail[1]), from, objectId: obj ? Number(obj) : undefined };
  }
  if (/^\/batch\/?$/.test(pathname)) return { kind: 'batch' };
  if (/^\/directory\/objects\/?$/.test(pathname)) return { kind: 'dir-objects' };
  if (/^\/directory\/departments\/?$/.test(pathname)) return { kind: 'dir-departments' };
  if (/^\/directory\/?$/.test(pathname)) return { kind: 'directory' };
  if (/^\/knowledge\/?$/.test(pathname)) return { kind: 'knowledge' };
  if (/^\/ai-settings\/?$/.test(pathname)) return { kind: 'ai-settings' };
  if (/^\/settings\/?$/.test(pathname)) return { kind: 'settings' };

  // Неизвестный путь → объекты (стартовая).
  return { kind: 'objects' };
}
