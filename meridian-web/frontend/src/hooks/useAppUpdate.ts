import { useEffect, useState } from 'react';

const POLL_MS = 60_000;
const VERSION_URL = '/version.json';

async function fetchBuildId(): Promise<string | null> {
  try {
    const r = await fetch(VERSION_URL, { cache: 'no-store' });
    if (!r.ok) return null;
    const j = await r.json();
    return typeof j?.buildId === 'string' ? j.buildId : null;
  } catch {
    return null;
  }
}

/**
 * Определяет, что на сервере лежит более новая сборка фронтенда, чем та,
 * что сейчас крутится в браузере: сравнивает зашитый __BUILD_ID__ со
 * статическим /version.json. Опрос раз в минуту + при возврате на вкладку.
 * После обнаружения опрос останавливается (ответ больше не изменится).
 */
export function useAppUpdate(): boolean {
  const [updateAvailable, setUpdateAvailable] = useState(false);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setInterval> | undefined;

    const stop = () => {
      stopped = true;
      if (timer) clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', check);
    };

    const check = async () => {
      if (stopped) return;
      const remote = await fetchBuildId();
      // Сетевые ошибки / битый JSON → null, флаг не поднимаем (транзиент).
      if (remote && remote !== __BUILD_ID__) {
        setUpdateAvailable(true);
        stop();
      }
    };

    const onVisible = () => {
      if (document.visibilityState === 'visible') check();
    };

    check();
    timer = setInterval(check, POLL_MS);
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', check);

    return stop;
  }, []);

  return updateAvailable;
}
