/**
 * Audio capture route types + presets (Этап 15).
 *
 * Route — это ТЕХНИЧЕСКИЙ маршрут захвата (какое устройство/микрофон), а НЕ сторона переговоров
 * и НЕ AI-профиль. Route никогда не используется для вывода speaker_side. Сторона приходит только
 * через speaker_identity_hints поверх stable link.
 *
 * Стрим в backend остаётся mono 16kHz (Этап 15 не меняет binary-протокол). idealSampleRate/
 * idealChannelCount задают только getUserMedia-хинты захвата; AudioContext ресемплит в 16kHz.
 */

export type AudioCaptureRoute =
  | 'browser_default'
  | 'laptop_mic'
  | 'usb_room_mic'
  | 'usb_recorder'
  | 'speakerphone_usb'
  | 'external_audio_interface'
  | 'phone_secondary'
  | 'unknown';

export type AudioCapturePipeline =
  | 'mono_stream'
  | 'stereo_requested_mono_stream'
  | 'multichannel_stream'
  | 'unknown';

export interface AudioConstraintPreset {
  route: AudioCaptureRoute;
  label: string;
  description: string;
  idealChannelCount: number;
  idealSampleRate: number;
  echoCancellation: boolean;
  noiseSuppression: boolean;
  autoGainControl: boolean;
}

/** Канонический sample rate стрима в backend. Этап 15 НЕ меняет его. */
export const AUDIO_STREAM_SAMPLE_RATE = 16000;

export const AUDIO_PRESETS: Record<AudioCaptureRoute, AudioConstraintPreset> = {
  browser_default: {
    route: 'browser_default',
    label: 'Браузер (по умолчанию)',
    description: 'Микрофон по умолчанию, обработка включена.',
    idealChannelCount: 1,
    idealSampleRate: 16000,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
  laptop_mic: {
    route: 'laptop_mic',
    label: 'Микрофон ноутбука',
    description: 'Встроенный микрофон, обработка включена.',
    idealChannelCount: 1,
    idealSampleRate: 16000,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
  speakerphone_usb: {
    route: 'speakerphone_usb',
    label: 'USB-спикерфон',
    description: 'Портативный конференц-спикерфон (Jabra/Poly/Anker).',
    idealChannelCount: 1,
    idealSampleRate: 16000,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
  usb_room_mic: {
    route: 'usb_room_mic',
    label: 'USB-микрофон в комнате',
    description: 'USB-микрофон по центру стола, без обработки.',
    idealChannelCount: 2,
    idealSampleRate: 48000,
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false,
  },
  usb_recorder: {
    route: 'usb_recorder',
    label: 'USB-рекордер (Zoom H2n)',
    description: 'Портативный рекордер как USB-аудио, без обработки.',
    idealChannelCount: 2,
    idealSampleRate: 48000,
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false,
  },
  external_audio_interface: {
    route: 'external_audio_interface',
    label: 'Внешняя аудиокарта',
    description: 'Аудиоинтерфейс/микшер, без обработки.',
    idealChannelCount: 2,
    idealSampleRate: 48000,
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false,
  },
  phone_secondary: {
    route: 'phone_secondary',
    label: 'Телефон (вторичный)',
    description: 'Запасной/secondary сценарий, не основной микрофон.',
    idealChannelCount: 1,
    idealSampleRate: 16000,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
  unknown: {
    route: 'unknown',
    label: 'Неизвестно',
    description: 'Маршрут не определён.',
    idealChannelCount: 1,
    idealSampleRate: 16000,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
};

/** Порядок показа в UI (phone_secondary — в конце как «запасной»). */
export const AUDIO_ROUTE_ORDER: AudioCaptureRoute[] = [
  'browser_default', 'laptop_mic', 'speakerphone_usb',
  'usb_room_mic', 'usb_recorder', 'external_audio_interface', 'phone_secondary',
];

export interface AudioInputDevice {
  deviceId: string;
  groupId?: string;
  label: string; // ТОЛЬКО для локального UI — в backend не отправляется
  isDefault: boolean;
  guessedRoute: AudioCaptureRoute;
}

export interface AudioCaptureSelection {
  deviceId: string | null; // null = браузерный default
  route: AudioCaptureRoute;
}

/** Безопасная metadata, отправляемая в backend. Без raw label/id — только хэши/категории. */
export interface AudioCaptureMetadataClient {
  route: AudioCaptureRoute;
  capturePipeline: AudioCapturePipeline;
  requestedChannelCount: number | null;
  actualChannelCount: number | null;
  requestedSampleRate: number | null;
  actualSampleRate: number | null;
  echoCancellation: boolean | null;
  noiseSuppression: boolean | null;
  autoGainControl: boolean | null;
  deviceLabelHash: string | null;
  deviceIdHash: string | null;
  browser: string | null;
  createdAtMs: number;
  // Этап 16: включён ли опциональный multichannel shadow-стрим (диагностика, не сторона/не STT)
  multichannelShadowEnabled?: boolean;
}

/** Маршруты, для которых имеет смысл предлагать multichannel shadow (multi-канальные устройства). */
export const MULTICHANNEL_CAPABLE_ROUTES: AudioCaptureRoute[] = [
  'usb_recorder', 'usb_room_mic', 'external_audio_interface',
];
