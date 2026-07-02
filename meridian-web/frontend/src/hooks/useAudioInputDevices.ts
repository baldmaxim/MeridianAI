import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  AudioCaptureRoute,
  AudioCaptureSelection,
  AudioInputDevice,
} from '../audio/audioCaptureTypes';
import {
  guessRouteFromLabel,
  loadAudioSelection,
  saveAudioSelection,
} from '../audio/audioCaptureMetadata';

/**
 * Управление списком input-устройств + выбором device/route (Этап 15).
 *
 * Raw label показываем только локально. Выбор (deviceId + route) персистится в localStorage; если
 * устройство пропало — fallback на browser default. Без сети. guessedRoute — UI-подсказка, не сторона.
 */
export function useAudioInputDevices() {
  const [devices, setDevices] = useState<AudioInputDevice[]>([]);
  const [selection, setSelection] = useState<AudioCaptureSelection>(() => loadAudioSelection());
  const [permissionGranted, setPermissionGranted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectionRef = useRef(selection);
  selectionRef.current = selection;

  const hasMedia = typeof navigator !== 'undefined' && !!navigator.mediaDevices;

  const refresh = useCallback(async (): Promise<AudioInputDevice[]> => {
    if (!hasMedia || !navigator.mediaDevices.enumerateDevices) return [];
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      const inputs = all
        .filter((d) => d.kind === 'audioinput')
        .map((d): AudioInputDevice => ({
          deviceId: d.deviceId,
          groupId: d.groupId || undefined,
          label: d.label || '',
          isDefault: d.deviceId === 'default' || d.deviceId === '',
          guessedRoute: guessRouteFromLabel(d.label),
        }));
      setDevices(inputs);
      if (inputs.some((d) => d.label)) setPermissionGranted(true);
      // Устройство пропало → fallback на default (route сохраняем).
      const sel = selectionRef.current;
      if (sel.deviceId && !inputs.some((d) => d.deviceId === sel.deviceId)) {
        const next = { ...sel, deviceId: null };
        setSelection(next);
        saveAudioSelection(next);
      }
      return inputs;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'enumerate failed');
      return [];
    }
  }, [hasMedia]);

  const requestPermission = useCallback(async (): Promise<void> => {
    if (!hasMedia || !navigator.mediaDevices.getUserMedia) {
      setError('Аудио недоступно в этом браузере');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop()); // только разблокировать labels, не держать mic
      setPermissionGranted(true);
      setError(null);
      await refresh();
    } catch (e) {
      const name = e instanceof DOMException ? e.name : '';
      setError(name === 'NotAllowedError'
        ? 'Доступ к микрофону запрещён'
        : (e instanceof Error ? e.message : 'Не удалось получить доступ к микрофону'));
    }
  }, [hasMedia, refresh]);

  const setDevice = useCallback((deviceId: string | null) => {
    setSelection((prev) => {
      const dev = devices.find((d) => d.deviceId === deviceId);
      // при выборе устройства подставляем угаданный route (если не unknown и текущий — default)
      let route = prev.route;
      if (dev && dev.guessedRoute !== 'unknown'
          && (prev.route === 'browser_default' || prev.route === 'unknown')) {
        route = dev.guessedRoute;
      }
      const next = { deviceId: deviceId || null, route };
      saveAudioSelection(next);
      return next;
    });
  }, [devices]);

  const setRoute = useCallback((route: AudioCaptureRoute) => {
    setSelection((prev) => {
      const next = { ...prev, route };
      saveAudioSelection(next);
      return next;
    });
  }, []);

  useEffect(() => {
    void refresh();
    if (!hasMedia || !navigator.mediaDevices.addEventListener) return;
    const onChange = () => { void refresh(); };
    navigator.mediaDevices.addEventListener('devicechange', onChange);
    return () => navigator.mediaDevices.removeEventListener('devicechange', onChange);
  }, [refresh, hasMedia]);

  return {
    devices,
    selection,
    permissionGranted,
    error,
    requestPermission,
    refresh,
    setDevice,
    setRoute,
  };
}
