import { useEffect, useRef, useState } from 'react';

const REFRESH_MS = 5 * 60 * 1000;

/** Опрос показателя: сразу, раз в 5 минут и при фокусе окна. Ошибка/загрузка — null. */
export const usePolledUsage = <T,>(fetcher: () => Promise<T>): T | null => {
  const [data, setData] = useState<T | null>(null);
  // fetcher держим в ref — эффект не перезапускается при смене ссылки на функцию
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    let alive = true;
    const load = () => {
      fetcherRef.current()
        .then((d) => { if (alive) setData(d); })
        .catch(() => { if (alive) setData(null); });
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    window.addEventListener('focus', load);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener('focus', load);
    };
  }, []);

  return data;
};
