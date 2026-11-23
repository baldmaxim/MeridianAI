import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { PublicSpeakerSide, DeviceSyncState, SecondaryShadowDiag } from '../types';
import { ClockSyncController } from '../lib/clockSync';
import { useWakeLock } from './useWakeLock';

// Этап 9.2: secondary audio shadow. Дополнительное устройство (device_role=secondary)
// стримит PCM16-чанки на backend для будущего multi-channel. На этом этапе чанки НЕ идут
// в STT и НЕ меняют активный источник аудио — только буферизуются и диагностируются.
//
// ОТЛИЧИЕ от observer: observer шлёт только числа (RMS/peak/VAD); shadow шлёт реальные
// аудио-чанки бинарными кадрами. Режимы не смешиваются.

function wsBase(): string {
  const env = import.meta.env.VITE_WS_URL;
  if (env) return env;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

const SAMPLE_RATE = 16000;
const CHANNELS = 1;
const CODEC = 'pcm16';
const CHUNK_SIZE = 1600; // 100мс @ 16кГц
// Переподключение WS при живом захвате: 1с, 2с, 4с, затем каждые 4с; после 5 неудач — прерывание.
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 4000;

// PCM-ворклет (Float32 → Int16), идентичен useAudioRecorder.
const WORKLET_CODE = `
  class PCMProcessor extends AudioWorkletProcessor {
    process(inputs) {
      const input = inputs[0]?.[0];
      if (input && input.length > 0) {
        const int16 = new Int16Array(input.length);
        for (let i = 0; i < input.length; i++) {
          const s = Math.max(-1, Math.min(1, input[i]));
          int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        this.port.postMessage(int16.buffer, [int16.buffer]);
      }
      return true;
    }
  }
  registerProcessor('pcm-processor', PCMProcessor);
`;

// Кадр: [uint16 BE header_len][JSON header utf8][PCM16 payload]
function buildFrame(header: object, pcm: Int16Array): ArrayBuffer {
  const headerBytes = new TextEncoder().encode(JSON.stringify(header));
  const buf = new ArrayBuffer(2 + headerBytes.length + pcm.byteLength);
  new DataView(buf).setUint16(0, headerBytes.length, false);
  new Uint8Array(buf, 2, headerBytes.length).set(headerBytes);
  new Uint8Array(buf, 2 + headerBytes.length).set(new Uint8Array(pcm.buffer));
  return buf;
}

function rmsOf(int16: Int16Array): number {
  let sum = 0;
  for (let i = 0; i < int16.length; i++) {
    const v = int16[i] / 0x8000;
    sum += v * v;
  }
  return int16.length ? Math.sqrt(sum / int16.length) : 0;
}

export function useSecondaryShadow(meetingId: number | null) {
  const [active, setActive] = useState(false);
  const [side, setSide] = useState<PublicSpeakerSide>('opponent');
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [sync, setSync] = useState<DeviceSyncState | null>(null);
  const [diag, setDiag] = useState<SecondaryShadowDiag | null>(null);
  // Захват оборвала ОС (экран погас / приложение свернули) или не удалось переподключить WS.
  const [interrupted, setInterrupted] = useState(false);
  // Wake Lock: экран не гаснет, пока помогаем (на iPhone при погашенном экране веб писать не может).
  const wakeLock = useWakeLock();

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const clockRef = useRef<ClockSyncController | null>(null);
  const seqRef = useRef(0);
  // true — захват не идёт (намеренный stop, прерывание или ещё не стартовал): обработчики молчат.
  const stoppedRef = useRef(true);
  const attemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const visHandlerRef = useRef<(() => void) | null>(null);
  const sideRef = useRef<PublicSpeakerSide>('opponent');
  useLayoutEffect(() => { sideRef.current = side; }, [side]);

  const clearReconnect = useCallback(() => {
    if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
    if (visHandlerRef.current) {
      document.removeEventListener('visibilitychange', visHandlerRef.current);
      visHandlerRef.current = null;
    }
  }, []);

  // Единый teardown (stop / прерывание / unmount). Обработчики снимаются ДО закрытия
  // ctx/треков/WS, иначе они сработают как ложное «прерывание» или запустят реконнект.
  const cleanup = useCallback(() => {
    stoppedRef.current = true;
    clearReconnect();
    if (clockRef.current) { clockRef.current.stop(); clockRef.current = null; }
    if (workletRef.current) {
      try { workletRef.current.port.onmessage = null; workletRef.current.disconnect(); } catch { /* ignore */ }
      workletRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onclose = null;
      try { wsRef.current.close(); } catch { /* ignore */ }
      wsRef.current = null;
    }
    if (ctxRef.current) {
      ctxRef.current.onstatechange = null;
      try { void ctxRef.current.close(); } catch { /* ignore */ }
      ctxRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => { t.onended = null; t.stop(); });
      streamRef.current = null;
    }
    setLevel(0);
  }, [clearReconnect]);

  const stop = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: 'disable_secondary_shadow' })); } catch { /* ignore */ }
    }
    cleanup();
    wakeLock.release();
    setActive(false);
    setReady(false);
    setSync(null);
    setDiag(null);
    setInterrupted(false);
  }, [cleanup, wakeLock]);

  // Прерывание захвата: штатная ситуация (не ошибка) — UI предложит «Продолжить помогать».
  const interrupt = useCallback(() => {
    if (stoppedRef.current) return;
    cleanup();
    wakeLock.release();
    setActive(false);
    setReady(false);
    setSync(null);
    setDiag(null);
    setError(null);
    setInterrupted(true);
  }, [cleanup, wakeLock]);

  const start = useCallback(async () => {
    if (meetingId == null) { setError('Нет встречи для второго канала'); return; }
    const token = localStorage.getItem('token');
    if (!token) { setError('Не авторизовано'); return; }

    // Захват жив: трек не завершён, контекст не закрыт/не прерван ОС.
    function captureAlive(): boolean {
      const ctx = ctxRef.current;
      const track = streamRef.current?.getAudioTracks()[0];
      if (!ctx || !track) return false;
      const st = ctx.state as string;
      return track.readyState === 'live' && st !== 'closed' && st !== 'interrupted';
    }

    // Открыть WS второго канала (первый раз и при переподключении). seq не сбрасывается.
    function openWs() {
      const ws = new WebSocket(`${wsBase()}/ws/meetings/${meetingId}?token=${token}&device_role=secondary`);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        attemptRef.current = 0;
        setError(null);
        ws.send(JSON.stringify({
          type: 'enable_secondary_shadow',
          sample_rate: SAMPLE_RATE, channels: CHANNELS, codec: CODEC, side_hint: sideRef.current,
        }));
        clockRef.current?.stop();
        clockRef.current = new ClockSyncController({
          send: (m) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(m)); },
          onResult: (st) => setSync(st),
        });
        clockRef.current.start();
      };

      ws.onmessage = (ev) => {
        if (typeof ev.data !== 'string') return;
        try {
          const m = JSON.parse(ev.data);
          switch (m.type) {
            case 'clock_pong': clockRef.current?.handlePong(m); break;
            case 'clock_sync_status':
              setSync({ offsetMs: m.offset_ms, rttMs: m.rtt_ms, quality: m.quality, samples: m.samples_count, lastSyncMs: Date.now() });
              break;
            case 'secondary_shadow_enabled': setReady(true); break;
            case 'secondary_shadow_diag': setDiag(m as SecondaryShadowDiag); break;
            case 'secondary_shadow_error': setError(`Второй канал отклонён: ${m.reason}`); stop(); break;
          }
        } catch { /* ignore */ }
      };

      ws.onerror = () => setError('Ошибка соединения второго канала');

      ws.onclose = () => {
        // Намеренный stop/прерывание или устаревший сокет — реконнект не нужен.
        if (stoppedRef.current || wsRef.current !== ws) return;
        setReady(false);
        if (clockRef.current) { clockRef.current.stop(); clockRef.current = null; }
        scheduleReconnect();
      };
    }

    function tryOpen() {
      if (stoppedRef.current) return;
      if (!captureAlive()) { interrupt(); return; }
      attemptRef.current += 1;
      openWs();
    }

    // Вкладка скрыта (экран погас) — таймеры в фоне ненадёжны: ждём возврата в видимость.
    function waitVisible() {
      if (visHandlerRef.current) return;
      const onVis = () => {
        if (document.visibilityState !== 'visible') return;
        document.removeEventListener('visibilitychange', onVis);
        visHandlerRef.current = null;
        tryOpen();
      };
      visHandlerRef.current = onVis;
      document.addEventListener('visibilitychange', onVis);
    }

    function scheduleReconnect() {
      clearReconnect();
      if (stoppedRef.current) return;
      if (attemptRef.current >= MAX_RECONNECT_ATTEMPTS) { interrupt(); return; }
      if (document.visibilityState !== 'visible') { waitVisible(); return; }
      const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attemptRef.current);
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        if (document.visibilityState !== 'visible') { waitVisible(); return; }
        tryOpen();
      }, delay);
    }

    setError(null);
    setInterrupted(false);
    seqRef.current = 0;
    attemptRef.current = 0;
    stoppedRef.current = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: SAMPLE_RATE, echoCancellation: true, noiseSuppression: true },
      });
      // stop()/unmount, пока ждали разрешение на микрофон — отпускаем только что выданный захват.
      if (stoppedRef.current) { stream.getTracks().forEach((t) => t.stop()); return; }
      streamRef.current = stream;
      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      ctxRef.current = ctx;

      // iOS: при блокировке экрана AudioContext уходит в 'interrupted'/'suspended', mic-трек
      // может завершиться. sawRunning гасит ложное 'suspended' на старте (до первого 'running').
      let sawRunning = (ctx.state as string) === 'running';
      ctx.onstatechange = () => {
        if (stoppedRef.current) return;
        const st = ctx.state as string;
        if (st === 'running') { sawRunning = true; return; }
        if (st === 'interrupted' || (st === 'suspended' && sawRunning)) interrupt();
      };
      stream.getAudioTracks().forEach((t) => {
        t.onended = () => { if (!stoppedRef.current) interrupt(); };
      });

      const blob = new Blob([WORKLET_CODE], { type: 'application/javascript' });
      const url = URL.createObjectURL(blob);
      await ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      // Прерывание/stop во время загрузки ворклета — захват уже снесён, дальше не строим.
      if (stoppedRef.current) return;

      const source = ctx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(ctx, 'pcm-processor');
      workletRef.current = worklet;

      openWs();

      let buffer = new Int16Array(0);
      worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        const newData = new Int16Array(event.data);
        const merged = new Int16Array(buffer.length + newData.length);
        merged.set(buffer);
        merged.set(newData, buffer.length);
        buffer = merged;
        while (buffer.length >= CHUNK_SIZE) {
          const chunk = buffer.slice(0, CHUNK_SIZE);
          buffer = buffer.slice(CHUNK_SIZE);
          const rms = rmsOf(chunk);
          setLevel(Math.min(1, rms * 2.5));
          // Сокет читаем из ref: после переподключения он другой. Пока не OPEN — кадр пропускаем.
          const cur = wsRef.current;
          if (!cur || cur.readyState !== WebSocket.OPEN) continue;
          const header = {
            seq: ++seqRef.current, client_ts_ms: Date.now(),
            sample_rate: SAMPLE_RATE, channels: CHANNELS, codec: CODEC,
            rms: Math.round(rms * 1e4) / 1e4,
          };
          cur.send(buildFrame(header, chunk));
        }
      };

      source.connect(worklet);
      // См. useAudioRecorder: тянем граф через MediaStreamAudioDestinationNode, чтобы
      // на iOS НЕ поднимать play-and-record сессию (системный звук старта в обход «без звука»).
      const sink = ctx.createMediaStreamDestination();
      worklet.connect(sink);

      setActive(true);
      void wakeLock.request();
    } catch {
      cleanup();
      wakeLock.release();
      setError('Не удалось получить доступ к микрофону');
    }
  }, [meetingId, cleanup, clearReconnect, stop, interrupt, wakeLock]);

  const setSideHint = useCallback((next: PublicSpeakerSide) => {
    setSide(next);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'secondary_shadow_side', side: next }));
    }
  }, []);

  useEffect(() => () => cleanup(), [cleanup]);  // unmount

  return { active, interrupted, side, level, error, ready, sync, diag, start, stop, setSideHint };
}
