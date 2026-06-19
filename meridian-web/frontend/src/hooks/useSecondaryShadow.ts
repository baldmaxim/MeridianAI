import { useCallback, useEffect, useRef, useState } from 'react';
import type { PublicSpeakerSide, DeviceSyncState, SecondaryShadowDiag } from '../types';
import { ClockSyncController } from '../lib/clockSync';

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

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const clockRef = useRef<ClockSyncController | null>(null);
  const seqRef = useRef(0);
  const sideRef = useRef<PublicSpeakerSide>('opponent');
  sideRef.current = side;

  const cleanup = useCallback(() => {
    if (clockRef.current) { clockRef.current.stop(); clockRef.current = null; }
    if (workletRef.current) { try { workletRef.current.disconnect(); } catch { /* ignore */ } workletRef.current = null; }
    if (wsRef.current) { try { wsRef.current.close(); } catch { /* ignore */ } wsRef.current = null; }
    if (ctxRef.current) { try { void ctxRef.current.close(); } catch { /* ignore */ } ctxRef.current = null; }
    if (streamRef.current) { streamRef.current.getTracks().forEach((t) => t.stop()); streamRef.current = null; }
    setLevel(0);
  }, []);

  const stop = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: 'disable_secondary_shadow' })); } catch { /* ignore */ }
    }
    cleanup();
    setActive(false);
    setReady(false);
    setSync(null);
    setDiag(null);
  }, [cleanup]);

  const start = useCallback(async () => {
    if (meetingId == null) { setError('Нет встречи для второго канала'); return; }
    const token = localStorage.getItem('token');
    if (!token) { setError('Не авторизовано'); return; }
    setError(null);
    seqRef.current = 0;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: SAMPLE_RATE, echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;
      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      ctxRef.current = ctx;

      const blob = new Blob([WORKLET_CODE], { type: 'application/javascript' });
      const url = URL.createObjectURL(blob);
      await ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);

      const source = ctx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(ctx, 'pcm-processor');
      workletRef.current = worklet;

      const wsUrl = `${wsBase()}/ws/meetings/${meetingId}?token=${token}&device_role=secondary`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
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
      ws.onclose = () => { /* остановка управляется stop() */ };

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
          if (ws.readyState !== WebSocket.OPEN) continue;
          const header = {
            seq: ++seqRef.current, client_ts_ms: Date.now(),
            sample_rate: SAMPLE_RATE, channels: CHANNELS, codec: CODEC,
            rms: Math.round(rms * 1e4) / 1e4,
          };
          ws.send(buildFrame(header, chunk));
        }
      };

      source.connect(worklet);
      const silent = ctx.createGain();
      silent.gain.value = 0;
      worklet.connect(silent);
      silent.connect(ctx.destination);

      setActive(true);
    } catch {
      cleanup();
      setError('Не удалось получить доступ к микрофону');
    }
  }, [meetingId, cleanup, stop]);

  const setSideHint = useCallback((next: PublicSpeakerSide) => {
    setSide(next);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'secondary_shadow_side', side: next }));
    }
  }, []);

  useEffect(() => () => cleanup(), [cleanup]);  // unmount

  return { active, side, level, error, ready, sync, diag, start, stop, setSideHint };
}
