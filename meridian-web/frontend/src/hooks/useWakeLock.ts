import { useCallback, useEffect, useMemo, useRef } from 'react';

/**
 * Screen Wake Lock — не даём экрану авто-гаснуть во время записи.
 *
 * Главный рычаг против «экран потух → запись прекратилась»: пока экран включён,
 * браузер не усыпляет вкладку и не прерывает AudioContext. Wake Lock авто-снимается
 * при скрытии вкладки (фон), поэтому пере-запрашиваем на возврат в видимость.
 *
 * Поддержка: iOS Safari 16.4+, Android Chrome. На старых устройствах — no-op.
 * ВАЖНО (iPhone): при ЗАБЛОКИРОВАННОМ/погашенном экране веб-страница писать
 * микрофон не может — это песочница Safari, Wake Lock лишь не даёт экрану гаснуть.
 */
export function useWakeLock() {
  const sentinelRef = useRef<WakeLockSentinel | null>(null);
  const wantedRef = useRef(false);

  const request = useCallback(async () => {
    wantedRef.current = true;
    if (!('wakeLock' in navigator)) return;
    if (sentinelRef.current) return;
    try {
      const s = await navigator.wakeLock.request('screen');
      sentinelRef.current = s;
      // ОС может снять lock сама (фон/смена вкладки) — сбрасываем ссылку.
      s.addEventListener('release', () => {
        if (sentinelRef.current === s) sentinelRef.current = null;
      });
    } catch {
      // Отказ политики/ОС — не критично, просто экран сможет погаснуть.
    }
  }, []);

  const release = useCallback(() => {
    wantedRef.current = false;
    const s = sentinelRef.current;
    sentinelRef.current = null;
    if (s) { try { void s.release(); } catch { /* ignore */ } }
  }, []);

  // Wake Lock снимается в фоне — пере-запрашиваем при возврате, если он ещё нужен.
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible' && wantedRef.current && !sentinelRef.current) {
        void request();
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [request]);

  // Снять lock при размонтировании.
  useEffect(() => () => {
    const s = sentinelRef.current;
    sentinelRef.current = null;
    if (s) { try { void s.release(); } catch { /* ignore */ } }
  }, []);

  // Стабильная ссылка — чтобы wakeLock в deps эффектов/колбэков не менялся каждый рендер.
  return useMemo(() => ({ request, release }), [request, release]);
}
