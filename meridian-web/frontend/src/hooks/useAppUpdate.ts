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

  /** Активирует ожидающий SW и перезагружает страницу. */
  const applyUpdate = () => updateServiceWorker(true);

  return { updateAvailable: needRefresh, applyUpdate };
}
