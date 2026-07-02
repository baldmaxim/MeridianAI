/**
 * Helpers для безопасной audio capture metadata (Этап 15).
 *
 * Backend получает ТОЛЬКО хэши device label/id + route/каналы/sample rate. Raw label/id остаются
 * на клиенте (label показываем локально в UI). route — техническая зона записи, НЕ сторона.
 */

import { AUDIO_PRESETS } from './audioCaptureTypes';
import type {
  AudioCaptureMetadataClient,
  AudioCapturePipeline,
  AudioCaptureRoute,
  AudioCaptureSelection,
  AudioConstraintPreset,
} from './audioCaptureTypes';

const STORAGE_KEY = 'meridian_audio_selection_v1';
const MC_SHADOW_KEY = 'meridian_audio_multichannel_shadow_enabled_v1';

/** Угадать route по label устройства — ТОЛЬКО UI-подсказка, не вывод стороны. */
export function guessRouteFromLabel(label: string | undefined | null): AudioCaptureRoute {
  const l = (label || '').toLowerCase();
  if (!l) return 'unknown';
  if (/(jabra|poly|plantronics|anker|speak|conference|speakerphone)/.test(l)) return 'speakerphone_usb';
  if (/(zoom|h2n|h1n|h2essential|h4n|h5|h6|tascam|rode|røde|dji|wireless go|zoom h)/.test(l)) return 'usb_recorder';
  if (/(scarlett|focusrite|audient|behringer|umc|presonus|motu|audio interface|usb audio codec)/.test(l)) {
    return 'external_audio_interface';
  }
  if (/(macbook|realtek|built-in|builtin|internal|laptop|внутренн|встроенн)/.test(l)) return 'laptop_mic';
  if (/(iphone|android|phone|телефон)/.test(l)) return 'phone_secondary';
  return 'unknown';
}

/** Короткое безопасное имя браузера (НЕ полный user-agent). */
export function shortBrowserName(): string | null {
  if (typeof navigator === 'undefined') return null;
  const ua = navigator.userAgent || '';
  if (/edg\//i.test(ua)) return 'Edge';
  if (/opr\//i.test(ua) || /opera/i.test(ua)) return 'Opera';
  if (/firefox/i.test(ua)) return 'Firefox';
  if (/chrome\//i.test(ua) && !/edg\//i.test(ua)) return 'Chrome';
  if (/safari/i.test(ua) && !/chrome/i.test(ua)) return 'Safari';
  return 'Other';
}

/** sha256[:16] токена через Web Crypto; fallback на синхронный 32-бит hex. None для пустого. */
export async function hashDeviceToken(value: string | null | undefined): Promise<string | null> {
  const s = (value || '').trim();
  if (!s) return null;
  try {
    if (typeof crypto !== 'undefined' && crypto.subtle) {
      const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
      const hex = Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
      return hex.slice(0, 16);
    }
  } catch {
    /* fall through to sync hash */
  }
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return ('00000000' + h.toString(16)).slice(-8);
}

export function presetForRoute(route: AudioCaptureRoute): AudioConstraintPreset {
  return AUDIO_PRESETS[route] || AUDIO_PRESETS.browser_default;
}

/** Pipeline-метка: stereo-запрос всё равно стримится как mono (Этап 15 не делает multichannel). */
export function pipelineForPreset(preset: AudioConstraintPreset): AudioCapturePipeline {
  return preset.idealChannelCount >= 2 ? 'stereo_requested_mono_stream' : 'mono_stream';
}

/** Собрать getUserMedia-constraints из пресета (+ exact deviceId, если выбран). */
export function constraintsFromPreset(
  preset: AudioConstraintPreset,
  deviceId: string | null,
): MediaStreamConstraints {
  const audio: MediaTrackConstraints = {
    channelCount: { ideal: preset.idealChannelCount },
    sampleRate: { ideal: preset.idealSampleRate },
    echoCancellation: preset.echoCancellation,
    noiseSuppression: preset.noiseSuppression,
    autoGainControl: preset.autoGainControl,
  };
  if (deviceId) audio.deviceId = { exact: deviceId };
  return { audio };
}

/** Текущий safe-fallback (как до Этапа 15): mono 16k, EC/NS. */
export const LEGACY_AUDIO_CONSTRAINTS: MediaStreamConstraints = {
  audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
};

/** Собрать безопасную metadata из пресета + actual track settings. Без raw label/id. */
export async function buildAudioCaptureMetadataClient(args: {
  preset: AudioConstraintPreset;
  deviceId: string | null;
  deviceLabel: string | null;
  settings: MediaTrackSettings | null;
  nowMs: number;
  multichannelShadowEnabled?: boolean;
}): Promise<AudioCaptureMetadataClient> {
  const { preset, deviceId, deviceLabel, settings, nowMs, multichannelShadowEnabled } = args;
  const s = settings || {};
  const [labelHash, idHash] = await Promise.all([
    hashDeviceToken(deviceLabel),
    hashDeviceToken(deviceId),
  ]);
  const num = (v: unknown): number | null => (typeof v === 'number' && isFinite(v) ? v : null);
  const bool = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null);
  return {
    route: preset.route,
    capturePipeline: pipelineForPreset(preset),
    requestedChannelCount: preset.idealChannelCount,
    actualChannelCount: num((s as MediaTrackSettings).channelCount),
    requestedSampleRate: preset.idealSampleRate,
    actualSampleRate: num((s as MediaTrackSettings).sampleRate),
    echoCancellation: bool((s as MediaTrackSettings).echoCancellation) ?? preset.echoCancellation,
    noiseSuppression: bool((s as MediaTrackSettings).noiseSuppression) ?? preset.noiseSuppression,
    autoGainControl: bool((s as MediaTrackSettings).autoGainControl) ?? preset.autoGainControl,
    deviceLabelHash: labelHash,
    deviceIdHash: idHash,
    browser: shortBrowserName(),
    createdAtMs: nowMs,
    multichannelShadowEnabled: !!multichannelShadowEnabled,
  };
}

export function loadMultichannelShadowEnabled(): boolean {
  try {
    if (typeof localStorage === 'undefined') return false;
    return localStorage.getItem(MC_SHADOW_KEY) === '1';
  } catch {
    return false;
  }
}

export function saveMultichannelShadowEnabled(enabled: boolean): void {
  try {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(MC_SHADOW_KEY, enabled ? '1' : '0');
  } catch {
    /* ignore */
  }
}

const VALID_ROUTES = new Set<string>(Object.keys(AUDIO_PRESETS));

export function loadAudioSelection(): AudioCaptureSelection {
  const fallback: AudioCaptureSelection = { deviceId: null, route: 'browser_default' };
  try {
    if (typeof localStorage === 'undefined') return fallback;
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<AudioCaptureSelection>;
    const route = (parsed.route && VALID_ROUTES.has(parsed.route)) ? parsed.route : 'browser_default';
    const deviceId = typeof parsed.deviceId === 'string' && parsed.deviceId ? parsed.deviceId : null;
    return { deviceId, route: route as AudioCaptureRoute };
  } catch {
    return fallback;
  }
}

export function saveAudioSelection(sel: AudioCaptureSelection): void {
  try {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ deviceId: sel.deviceId, route: sel.route }));
  } catch {
    /* ignore quota/availability errors */
  }
}
