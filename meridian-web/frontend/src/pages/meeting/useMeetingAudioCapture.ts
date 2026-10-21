import { useCallback, useEffect, useRef, useState } from 'react';
import { useAudioRecorder } from '../../hooks/useAudioRecorder';
import type { AudioRecorderCaptureConfig, AudioSourceLevels, SystemAudioState } from '../../hooks/useAudioRecorder';
import { useWakeLock } from '../../hooks/useWakeLock';
import { useMeetingStore } from '../../store/meetingStore';
import { MULTICHANNEL_CAPABLE_ROUTES } from '../../audio/audioCaptureTypes';
import {
  SystemAudioError,
  SYSTEM_AUDIO_ERROR_TEXT,
  captureSystemAudio,
  isSystemAudioSupported,
  stopSystemAudio,
} from '../../audio/systemAudio';
import {
  loadAudioSelection,
  loadMultichannelShadowEnabled,
  loadOnlineMeetingAudioEnabled,
  presetForRoute,
  saveOnlineMeetingAudioEnabled,
} from '../../audio/audioCaptureMetadata';
import { uploadBatchAudio } from '../../api/batch';
import { offlineAudioBuffer } from '../../lib/offlineAudioBuffer';
import type { WSMessageToServer } from '../../types';

type TShowToast = (message: string, type?: 'success' | 'error') => void;

interface IUseMeetingAudioCaptureParams {
  sendJSON: (msg: WSMessageToServer) => void;
  sendBinary: (data: ArrayBuffer) => void;
  /** Текущий WebSocket встречи (читается в момент отправки, не при рендере). */
  getSocket: () => WebSocket | null;
  isConnected: boolean;
  showToast: TShowToast;
  /** Вернуть существующую встречу или создать новую и подключиться (null — не удалось). */
  startSession: (forceNew?: boolean) => Promise<number | null>;
  waitForConnected: (timeoutMs?: number) => Promise<boolean>;
}

/**
 * Задача 5: при восстановлении WS (false→true) дослать накопленный офлайн-звук
 * как офлайн-дозапись (kind=gap_fill) — результат вливается в транскрипт встречи.
 */
const useOfflineAudioFlush = (isConnected: boolean, showToast: TShowToast) => {
  const prevConnectedRef = useRef(false);
  const flushingRef = useRef(false);
  useEffect(() => {
    const wasConnected = prevConnectedRef.current;
    prevConnectedRef.current = isConnected;
    if (!isConnected || wasConnected || flushingRef.current) return;
    const mid = useMeetingStore.getState().currentMeetingId;
    if (mid == null) return;
    flushingRef.current = true;
    (async () => {
      try {
        const wav = await offlineAudioBuffer.drainToWav(mid);
        if (wav) {
          const file = new File([wav], `gap_${mid}_${Date.now()}.wav`, { type: 'audio/wav' });
          await uploadBatchAudio(file, undefined, { meetingId: mid, kind: 'gap_fill' });
          showToast('Аудио из офлайна отправлено на дораспознавание', 'success');
        }
      } catch {
        showToast('Не удалось отправить офлайн-аудио', 'error');
      } finally {
        flushingRef.current = false;
      }
    })();
  }, [isConnected, showToast]);
};

/** Запись аудио встречи: микрофон + звук встречи (онлайн), старт/стоп/возобновление, офлайн-буфер. */
export const useMeetingAudioCapture = ({
  sendJSON, sendBinary, getSocket, isConnected, showToast, startSession, waitForConnected,
}: IUseMeetingAudioCaptureParams) => {
  const [level, setLevel] = useState(0);
  // Задача 5: если WS открыт — чанк идёт в realtime STT; иначе буферизуем в IndexedDB
  // (переживает обрыв/перезагрузку) и дошлём батчем при восстановлении сети.
  const sendAudioChunk = useCallback((buf: ArrayBuffer) => {
    if (getSocket()?.readyState === WebSocket.OPEN) { sendBinary(buf); return; }
    const mid = useMeetingStore.getState().currentMeetingId;
    if (mid != null) void offlineAudioBuffer.append(mid, buf);
  }, [sendBinary, getSocket]);
  // Wake Lock держит экран включённым, пока идёт запись (мобильный фон/блокировка).
  const wakeLock = useWakeLock();
  // Запись прервана ОС (экран заблокирован / звонок) — показываем «Продолжить».
  const [recordingPaused, setRecordingPaused] = useState(false);
  const onAudioInterrupt = useCallback(() => {
    if (useMeetingStore.getState().isListening) setRecordingPaused(true);
  }, []);
  // Этап 15: текущий конфиг захвата (device/route). Инициализируем из localStorage, чтобы запись
  // без открытия панели использовала сохранённый выбор. Панель обновляет ref через onConfigChange.
  // Панель живёт в выпадающих «Настройках» и может быть ни разу не открыта — shadow-флаг тоже отсюда.
  const audioCaptureRef = useRef<AudioRecorderCaptureConfig>({
    deviceId: loadAudioSelection().deviceId,
    preset: presetForRoute(loadAudioSelection().route),
    multichannelShadowEnabled: loadMultichannelShadowEnabled()
      && MULTICHANNEL_CAPABLE_ROUTES.includes(loadAudioSelection().route),
  });
  const onAudioCaptureConfig = useCallback((cfg: AudioRecorderCaptureConfig) => {
    audioCaptureRef.current = cfg;
  }, []);
  // Этап 16: v2 shadow-кадр уходит ТОЛЬКО если ws открыт и буфер не переполнен. Legacy mono
  // (sendAudioChunk) никогда не дропается из-за shadow — приоритет у production STT.
  const sendShadowFrame = useCallback((buf: ArrayBuffer) => {
    const w = getSocket();
    if (w?.readyState === WebSocket.OPEN && w.bufferedAmount < 1_000_000) sendBinary(buf);
  }, [sendBinary, getSocket]);
  // Онлайн-встреча: захват звука вкладки/экрана. Держим и в ref — getConfig() читается
  // на каждом start(), а AudioPreflightPanel перезаписывает audioCaptureRef целиком.
  const [onlineAudio, setOnlineAudio] = useState(() => loadOnlineMeetingAudioEnabled());
  const onlineAudioRef = useRef(onlineAudio);
  useEffect(() => { onlineAudioRef.current = onlineAudio; }, [onlineAudio]);
  const [systemAudioState, setSystemAudioState] = useState<SystemAudioState | null>(null);
  const [sourceLevels, setSourceLevels] = useState<AudioSourceLevels | null>(null);
  const sourceLevelsSeq = useRef(0);
  const handleOnlineAudioToggle = useCallback((next: boolean) => {
    setOnlineAudio(next);
    saveOnlineMeetingAudioEnabled(next);
    if (!next) { setSystemAudioState(null); setSourceLevels(null); }
  }, []);
  // Уровни двух источников (~150 мс): по ним backend помечает, чья это реплика.
  // Числа, не аудио. Шлём только во время записи и только при живом WS.
  const sourceLevelsWasActive = useRef(false);
  const handleSourceLevels = useCallback((levels: AudioSourceLevels) => {
    setSourceLevels(levels);
    // На очной встрече (захват выключен) слать нечего: сторону по одному микрофону
    // не определить. Один кадр после отключения нужен, чтобы backend снял виртуальные
    // устройства и перестал считать сторону по устаревшим уровням.
    const wasActive = sourceLevelsWasActive.current;
    sourceLevelsWasActive.current = levels.systemActive;
    if (!levels.systemActive && !wasActive) return;
    sendJSON({
      type: 'audio_source_levels',
      mic_rms: levels.micRms,
      mic_peak: levels.micPeak,
      system_rms: levels.systemRms,
      system_peak: levels.systemPeak,
      system_active: levels.systemActive,
      seq: ++sourceLevelsSeq.current,
      client_ts_ms: Date.now(),
    });
  }, [sendJSON]);
  const handleSystemAudioState = useCallback((state: SystemAudioState) => {
    setSystemAudioState(state);
    if (state.error && state.message) showToast(state.message, 'error');
    else if (!state.active && !state.error) showToast('Доступ к звуку встречи прекращён — пишем только микрофон', 'error');
  }, [showToast]);

  const { start: startAudio, stop: stopAudio } = useAudioRecorder(
    sendAudioChunk, setLevel, onAudioInterrupt,
    {
      getConfig: () => ({
        ...audioCaptureRef.current,
        systemAudioEnabled: onlineAudioRef.current,
      }),
      onCaptureMetadata: (m) => sendJSON({ type: 'audio_capture_metadata', payload: m }),
      sendShadowFrame,
      onSourceLevels: handleSourceLevels,
      onSystemAudioState: handleSystemAudioState,
    },
  );

  useOfflineAudioFlush(isConnected, showToast);

  const handleStartListening = useCallback(async () => {
    const store = useMeetingStore.getState();
    // Этап 3: если активный источник аудио — другое устройство (телефон), не стартуем
    let st = useMeetingStore.getState();
    if (st.activeAudioSource && st.activeAudioSource !== st.connectionId) {
      store.setError('Источник аудио занят (идёт запись с устройства)');
      return;
    }
    // Звук встречи запрашиваем ДО любых await: getDisplayMedia работает только по свежему
    // клику, а ниже мы можем успеть создать встречу и дождаться WS. Отказ не отменяет запись.
    let systemStream: MediaStream | null = null;
    if (onlineAudioRef.current && isSystemAudioSupported()) {
      try {
        systemStream = await captureSystemAudio();
      } catch (err) {
        const code = err instanceof SystemAudioError ? err.code : 'failed';
        handleSystemAudioState({ active: false, error: code, message: SYSTEM_AUDIO_ERROR_TEXT[code] });
      }
    }
    const abort = (message: string) => {
      stopSystemAudio(systemStream);
      store.setError(message);
    };
    // Встреча создаётся вручную при первом старте записи (не при заходе на портал).
    if (st.currentMeetingId == null || !st.isConnected) {
      const id = await startSession(false);
      if (id == null) { abort('Не удалось создать встречу'); return; }
      const ok = await waitForConnected();
      if (!ok) { abort('Не удалось подключиться к встрече'); return; }
      st = useMeetingStore.getState();
      if (st.activeAudioSource && st.activeAudioSource !== st.connectionId) {
        abort('Источник аудио занят (идёт запись с устройства)');
        return;
      }
    }
    try {
      await startAudio(systemStream);
      void wakeLock.request();
      setRecordingPaused(false);
      sendJSON({ type: 'start_audio' });
      store.setListening(true);
    } catch {
      abort('Не удалось получить доступ к микрофону');
    }
  }, [startAudio, sendJSON, startSession, waitForConnected, wakeLock, handleSystemAudioState]);

  const handleStopListening = useCallback(() => {
    stopAudio();
    wakeLock.release();
    setRecordingPaused(false);
    sendJSON({ type: 'stop_audio' });
    useMeetingStore.getState().setListening(false);
  }, [stopAudio, sendJSON, wakeLock]);

  // Возобновление после прерывания ОС: пересоздаём захват (старый трек/контекст мертвы).
  // Тап по кнопке = гарантированный user-gesture, который iOS требует для getUserMedia.
  const handleResumeListening = useCallback(async () => {
    try {
      stopAudio();
      await startAudio();
      void wakeLock.request();
      sendJSON({ type: 'start_audio' });
      setRecordingPaused(false);
    } catch {
      useMeetingStore.getState().setError('Не удалось возобновить запись');
    }
  }, [stopAudio, startAudio, sendJSON, wakeLock]);

  return {
    level,
    recordingPaused,
    onlineAudio,
    systemAudioState,
    sourceLevels,
    onAudioCaptureConfig,
    handleOnlineAudioToggle,
    handleStartListening,
    handleStopListening,
    handleResumeListening,
  };
};
