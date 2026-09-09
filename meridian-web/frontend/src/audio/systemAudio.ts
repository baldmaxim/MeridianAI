/**
 * Захват звука онлайн-встречи (Zoom / Teams / Google Meet) через getDisplayMedia.
 *
 * Зачем: в онлайне голос второй стороны идёт в наушники/колонки, а не в микрофон
 * (и echoCancellation микрофона его дополнительно вырезает). Без этого захвата ассистент
 * слышит только нашу сторону и строит подсказки по половине разговора.
 *
 * Что делаем: просим у браузера вкладку или весь экран ВМЕСТЕ со звуком, видео-дорожку
 * не используем (держим на 1 fps только потому, что без video браузер не предложит звук).
 * Полученный поток микшируется с микрофоном в тот же mono 16 кГц PCM — бинарный протокол
 * не меняется.
 *
 * Ограничения браузеров:
 *   - Chrome / Edge: вкладка со звуком — везде; «весь экран + системный звук» — Windows.
 *   - Firefox / Safari: звук экрана не отдают → показываем понятную ошибку, запись
 *     продолжается только с микрофона.
 */

export type SystemAudioErrorCode = 'unsupported' | 'denied' | 'no_audio' | 'failed';

export class SystemAudioError extends Error {
  code: SystemAudioErrorCode;

  constructor(code: SystemAudioErrorCode, message: string) {
    super(message);
    this.name = 'SystemAudioError';
    this.code = code;
  }
}

export const SYSTEM_AUDIO_ERROR_TEXT: Record<SystemAudioErrorCode, string> = {
  unsupported: 'Браузер не умеет захватывать звук встречи. Используйте Chrome или Edge.',
  denied: 'Доступ к звуку встречи не выдан — пишем только микрофон.',
  no_audio: 'Вы не включили «Поделиться звуком» в окне выбора — слышно только вас. Включите запись заново и поставьте галочку.',
  failed: 'Не удалось захватить звук встречи — пишем только микрофон.',
};

/** Поддерживает ли браузер захват экрана/вкладки в принципе. */
export function isSystemAudioSupported(): boolean {
  return typeof navigator !== 'undefined'
    && !!navigator.mediaDevices
    && typeof navigator.mediaDevices.getDisplayMedia === 'function';
}

/**
 * Запросить у пользователя вкладку/экран со звуком.
 *
 * Возвращает MediaStream, в котором ГАРАНТИРОВАННО есть аудио-дорожка. Видео-дорожку
 * оставляем живой (в Chrome её остановка обрывает весь захват), но нигде не рендерим.
 * Бросает SystemAudioError с понятным кодом — вызывающий не должен ломать запись.
 */
export async function captureSystemAudio(): Promise<MediaStream> {
  if (!isSystemAudioSupported()) {
    throw new SystemAudioError('unsupported', SYSTEM_AUDIO_ERROR_TEXT.unsupported);
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      // video обязателен: без него Chrome не покажет выбор вкладки и не отдаст звук.
      // 1 fps + маленький кадр — чтобы захват экрана не грел процессор во время встречи.
      video: { frameRate: { ideal: 1, max: 2 }, width: { max: 640 } },
      audio: {
        // Звук встречи берём как есть: обработка микрофонных алгоритмов тут только портит.
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        // ВАЖНО: false — иначе пользователь перестанет слышать собеседника в колонках.
        suppressLocalAudioPlayback: false,
      } as MediaTrackConstraints,
    });
  } catch (err) {
    const name = (err as { name?: string } | null)?.name || '';
    if (name === 'NotAllowedError' || name === 'AbortError' || name === 'SecurityError') {
      throw new SystemAudioError('denied', SYSTEM_AUDIO_ERROR_TEXT.denied);
    }
    throw new SystemAudioError('failed', SYSTEM_AUDIO_ERROR_TEXT.failed);
  }

  if (stream.getAudioTracks().length === 0) {
    // Пользователь выбрал источник, но забыл галочку «Поделиться звуком».
    stream.getTracks().forEach((t) => t.stop());
    throw new SystemAudioError('no_audio', SYSTEM_AUDIO_ERROR_TEXT.no_audio);
  }

  return stream;
}

/**
 * Подписаться на «пользователь нажал Прекратить доступ» (или вкладка закрылась).
 * Возвращает функцию отписки.
 */
export function onSystemAudioEnded(stream: MediaStream, handler: () => void): () => void {
  const tracks = stream.getTracks();
  tracks.forEach((t) => t.addEventListener('ended', handler));
  return () => tracks.forEach((t) => t.removeEventListener('ended', handler));
}

/** Остановить все дорожки захвата (аудио + служебное видео). */
export function stopSystemAudio(stream: MediaStream | null): void {
  if (!stream) return;
  stream.getTracks().forEach((t) => {
    try { t.stop(); } catch { /* уже остановлена */ }
  });
}
