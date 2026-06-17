import { useCallback, useEffect, useRef, useState } from 'react';
import type { PublicSpeakerSide } from '../types';

// Этап 9: observer-устройство (второй телефон). Считает уровень звука локально и шлёт
// ТОЛЬКО числовые метрики (rms/peak/vad) по своему WS как device_role=observer.
// НЕ отправляет raw audio, НЕ становится активным STT-источником.

function wsBase(): string {
  const env = import.meta.env.VITE_WS_URL;
  if (env) return env;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

const SEND_INTERVAL_MS = 150;
const VAD_RMS = 0.02;

export function useObserverMic(meetingId: number | null) {
  const [active, setActive] = useState(false);
  const [side, setSide] = useState<PublicSpeakerSide>('opponent');
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seqRef = useRef(0);
  const sideRef = useRef<PublicSpeakerSide>('opponent');
  sideRef.current = side;

  const cleanup = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    if (wsRef.current) { try { wsRef.current.close(); } catch { /* ignore */ } wsRef.current = null; }
    if (ctxRef.current) { try { void ctxRef.current.close(); } catch { /* ignore */ } ctxRef.current = null; }
    if (streamRef.current) { streamRef.current.getTracks().forEach((t) => t.stop()); streamRef.current = null; }
    analyserRef.current = null;
    setLevel(0);
  }, []);

  const stop = useCallback(() => {
    cleanup();
    setActive(false);
  }, [cleanup]);

  const start = useCallback(async () => {
    if (meetingId == null) { setError('Нет встречи для наблюдения'); return; }
    const token = localStorage.getItem('token');
    if (!token) { setError('Не авторизовано'); return; }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const srcNode = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      srcNode.connect(analyser);  // НЕ подключаем к destination — звук не воспроизводим
      analyserRef.current = analyser;

      const url = `${wsBase()}/ws/meetings/${meetingId}?token=${token}&device_role=observer`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'observer_side', side: sideRef.current }));
      };
      ws.onerror = () => setError('Ошибка соединения наблюдателя');
      ws.onclose = () => { /* остановка управляется stop() */ };

      const buf = new Float32Array(analyser.fftSize);
      timerRef.current = setInterval(() => {
        const a = analyserRef.current;
        if (!a || ws.readyState !== WebSocket.OPEN) return;
        a.getFloatTimeDomainData(buf);
        let sum = 0;
        let peak = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = buf[i];
          sum += v * v;
          const av = Math.abs(v);
          if (av > peak) peak = av;
        }
        const rms = Math.sqrt(sum / buf.length);
        setLevel(rms);
        ws.send(JSON.stringify({
          type: 'audio_level', rms, peak, vad: rms > VAD_RMS,
          seq: ++seqRef.current, client_ts_ms: Date.now(),
        }));
      }, SEND_INTERVAL_MS);

      setActive(true);
    } catch {
      cleanup();
      setError('Не удалось получить доступ к микрофону');
    }
  }, [meetingId, cleanup]);

  const setSideHint = useCallback((next: PublicSpeakerSide) => {
    setSide(next);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'observer_side', side: next }));
    }
  }, []);

  useEffect(() => () => cleanup(), [cleanup]);  // unmount

  return { active, side, level, error, start, stop, setSideHint };
}
