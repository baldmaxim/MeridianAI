import { useCallback, useEffect, useRef, useState } from 'react';
import type { AudioConstraintPreset } from '../audio/audioCaptureTypes';
import { constraintsFromPreset } from '../audio/audioCaptureMetadata';

export type SoundCheckStatus =
  | 'idle' | 'requesting_permission' | 'running' | 'ok' | 'too_quiet' | 'clipping' | 'error';

export interface SoundCheckState {
  status: SoundCheckStatus;
  rmsLevel: number;
  peakLevel: number;
  clippingDetected: boolean;
  silenceDetected: boolean;
  sampleRate: number | null;
  channelCount: number | null;
  error: string | null;
}

const SILENCE_RMS = 0.012;
const SILENCE_MS = 1500;
const CLIP_PEAK = 0.98;
const CLIP_HOLD_MS = 1500;
const WARMUP_MS = 700;
const UI_THROTTLE_MS = 80;

/**
 * Локальный sound-check (Этап 15): уровень/тишина/клиппинг/sample rate/каналы.
 * НЕ хранит и НЕ загружает аудио, НЕ ходит в backend, закрывает mic после stop/unmount.
 */
export function useAudioSoundCheck() {
  const [state, setState] = useState<SoundCheckState>({
    status: 'idle', rmsLevel: 0, peakLevel: 0, clippingDetected: false,
    silenceDetected: false, sampleRate: null, channelCount: null, error: null,
  });

  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);
  const startedAtRef = useRef(0);
  const lastNonSilentRef = useRef(0);
  const lastClipRef = useRef(0);
  const lastUiRef = useRef(0);

  const stop = useCallback(() => {
    if (rafRef.current != null) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    if (ctxRef.current) { try { ctxRef.current.close(); } catch { /* ignore */ } ctxRef.current = null; }
    if (streamRef.current) { streamRef.current.getTracks().forEach((t) => t.stop()); streamRef.current = null; }
    setState((s) => ({ ...s, status: 'idle', rmsLevel: 0, peakLevel: 0 }));
  }, []);

  const start = useCallback(async (deviceId: string | null, preset: AudioConstraintPreset) => {
    stop();
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setState((s) => ({ ...s, status: 'error', error: 'Аудио недоступно' }));
      return;
    }
    setState((s) => ({ ...s, status: 'requesting_permission', error: null }));
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia(constraintsFromPreset(preset, deviceId));
    } catch {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: deviceId ? { deviceId } : true });
      } catch (e2) {
        setState((s) => ({ ...s, status: 'error',
          error: e2 instanceof Error ? e2.message : 'Не удалось открыть микрофон' }));
        return;
      }
    }
    streamRef.current = stream;
    const track = stream.getAudioTracks()[0];
    const settings = track?.getSettings?.() || {};
    const ctx = new AudioContext();
    ctxRef.current = ctx;
    const src = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    src.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);

    const now0 = ctx.currentTime * 1000;
    startedAtRef.current = now0;
    lastNonSilentRef.current = now0;
    lastClipRef.current = -CLIP_HOLD_MS;
    lastUiRef.current = 0;

    setState((s) => ({
      ...s, status: 'running', error: null,
      sampleRate: typeof settings.sampleRate === 'number' ? settings.sampleRate : ctx.sampleRate,
      channelCount: typeof settings.channelCount === 'number' ? settings.channelCount : null,
    }));

    const tick = () => {
      const ctxNow = ctxRef.current;
      if (!ctxNow) return;
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      let peak = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = buf[i];
        sum += v * v;
        const a = Math.abs(v);
        if (a > peak) peak = a;
      }
      const rms = Math.sqrt(sum / buf.length);
      const tMs = ctxNow.currentTime * 1000;
      if (rms >= SILENCE_RMS) lastNonSilentRef.current = tMs;
      if (peak >= CLIP_PEAK) lastClipRef.current = tMs;
      const silence = tMs - lastNonSilentRef.current > SILENCE_MS;
      const clipping = tMs - lastClipRef.current < CLIP_HOLD_MS;
      const warmed = tMs - startedAtRef.current > WARMUP_MS;

      if (tMs - lastUiRef.current >= UI_THROTTLE_MS) {
        lastUiRef.current = tMs;
        let status: SoundCheckStatus = 'running';
        if (warmed) status = clipping ? 'clipping' : (silence ? 'too_quiet' : 'ok');
        setState((s) => ({
          ...s, status,
          rmsLevel: Math.min(1, rms * 2.5),
          peakLevel: Math.min(1, peak),
          clippingDetected: clipping,
          silenceDetected: silence,
        }));
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [stop]);

  useEffect(() => stop, [stop]); // cleanup on unmount

  return { ...state, start, stop };
}
