import { useCallback, useEffect, useRef, useState } from 'react';
import type { WSMessageToServer } from '../types';

const isTypingTarget = (target: EventTarget | null): boolean => {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable;
};

/**
 * Кнопка «держу — говорим мы»: нажатие/отпускание уходит на сервер с временем клиента,
 * сервер сопоставляет удержание с репликами и закрепляет сторону за голосом.
 * На ПК то же самое — удержание клавиши M. Отпускание при уходе со вкладки/потере фокуса.
 */
export const useSelfHold = (enabled: boolean, sendJSON: (msg: WSMessageToServer) => void) => {
  const [holding, setHolding] = useState(false);
  const holdingRef = useRef(false);

  const press = useCallback(() => {
    if (!enabled || holdingRef.current) return;
    holdingRef.current = true;
    setHolding(true);
    sendJSON({ type: 'self_hold', holding: true, client_ts_ms: Date.now() });
    navigator.vibrate?.(15);
  }, [enabled, sendJSON]);

  const release = useCallback(() => {
    if (!holdingRef.current) return;
    holdingRef.current = false;
    setHolding(false);
    sendJSON({ type: 'self_hold', holding: false, client_ts_ms: Date.now() });
  }, [sendJSON]);

  useEffect(() => {
    if (!enabled) return undefined;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'KeyM' || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      e.preventDefault();
      press();
    };
    const onKeyUp = (e: KeyboardEvent) => { if (e.code === 'KeyM') release(); };
    const onVisibility = () => { if (document.visibilityState !== 'visible') release(); };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', release);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', release);
      document.removeEventListener('visibilitychange', onVisibility);
      // Запись остановили/калибровка выключилась, пока кнопку держали — отпускаем.
      release();
    };
  }, [enabled, press, release]);

  return { holding, press, release };
};
