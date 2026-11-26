import { useEffect, useState } from 'react';
import type { RefObject } from 'react';
import type { IAlignedToken } from './alignWords';

/** Опережение: слово подсвечивается чуть раньше его начала, чтобы глаз не отставал. */
const LEAD = 0.05;
/** После конца слова подсветка держится столько секунд; дальше (пауза в речи) — гаснет. */
const HOLD = 0.6;

/**
 * Индекс токена, звучащего сейчас: последнего со start <= currentTime+LEAD (-1 — до первого слова,
 * в паузе дольше HOLD после конца слова или выключено). Пока аудио играет — цикл requestAnimationFrame
 * (timeupdate слишком редкий для слов); state меняется только при смене индекса.
 */
export const useActiveWord = (
  audioRef: RefObject<HTMLAudioElement | null>,
  tokens: IAlignedToken[] | null,
  enabled: boolean,
): number => {
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const audio = audioRef.current;
    if (!enabled || !audio || !tokens) return;
    let frame = 0;
    const update = () => {
      const now = audio.currentTime;
      let index = -1;
      for (let i = 0; i < tokens.length; i += 1) {
        const start = tokens[i].start;
        if (start !== null && start <= now + LEAD) index = i;
      }
      if (index !== -1) {
        const end = tokens[index].end;
        if (end !== null && now > end + HOLD) index = -1;
      }
      setActive((prev) => (prev === index ? prev : index));
    };
    const tick = () => {
      update();
      frame = requestAnimationFrame(tick);
    };
    const startLoop = () => {
      if (frame === 0) frame = requestAnimationFrame(tick);
    };
    const stopLoop = () => {
      if (frame !== 0) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    };
    const handleStop = () => {
      stopLoop();
      update();
    };
    update();
    if (!audio.paused) startLoop();
    audio.addEventListener('play', startLoop);
    audio.addEventListener('playing', startLoop);
    audio.addEventListener('pause', handleStop);
    audio.addEventListener('ended', handleStop);
    audio.addEventListener('seeked', update);
    audio.addEventListener('timeupdate', update);
    return () => {
      stopLoop();
      audio.removeEventListener('play', startLoop);
      audio.removeEventListener('playing', startLoop);
      audio.removeEventListener('pause', handleStop);
      audio.removeEventListener('ended', handleStop);
      audio.removeEventListener('seeked', update);
      audio.removeEventListener('timeupdate', update);
    };
  }, [audioRef, tokens, enabled]);

  return enabled && tokens ? active : -1;
};
