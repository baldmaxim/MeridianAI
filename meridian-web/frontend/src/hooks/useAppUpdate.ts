import { useRegisterSW } from 'virtual:pwa-register/react';

/** Как часто просить браузер проверить новый service worker. */
export const SW_UPDATE_INTERVAL_MS = 30 * 60 * 1000;

let updateTimer: ReturnType<typeof setInterval> | undefined;

/**
 * Регистрирует service worker (vite-plugin-pwa, registerType: 'prompt') и сообщает,
 * что готова новая версия фронтенда. Молчаливого skipWaiting нет: новая версия
 * применяется только по явному `applyUpdate()` (кнопка «Обновить» в тосте).
 * Раз в 30 минут вызывает registration.update(). Вызывать один раз — из AppUpdateBanner.
 */
export function useAppUpdate() {
  const {
    needRefresh: [needRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW: (_swUrl, registration) => {
      if (!registration || updateTimer) return;
      updateTimer = setInterval(() => {
        if (navigator.onLine === false) return;
        registration.update().catch(() => {
          /* нет сети / сервер недоступен — повторим на следующем тике */
        });
      }, SW_UPDATE_INTERVAL_MS);
    },
  });

  /**
   * Активирует ожидающий SW и перезагружает страницу. Перезагрузку делаем сами:
   * плагин перезагружает только при `controlling.isUpdate`, а его нет, если страницу
   * открыли без активного SW (первый заход, Ctrl+Shift+R) — тогда кнопка «молчала».
   */
  const applyUpdate = async () => {
    let done = false;
    const reload = () => {
      if (done) return;
      done = true;
      window.location.reload();
    };
    const waiting = (await navigator.serviceWorker?.getRegistration())?.waiting;
    if (!waiting) return reload(); // уже активирован (другой вкладкой) — просто перезагрузить
    navigator.serviceWorker.addEventListener('controllerchange', reload, { once: true });
    waiting.addEventListener('statechange', () => {
      if (waiting.state === 'activated') reload();
    });
    void updateServiceWorker(true); // шлёт SKIP_WAITING ожидающему SW
    setTimeout(reload, 4000); // страховка, если события не пришли
  };

  return { updateAvailable: needRefresh, applyUpdate };
}
