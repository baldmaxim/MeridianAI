import { useEffect, useState } from 'react';
import type { RefObject } from 'react';

/** Допуск: после перемотки к start браузер может округлить currentTime чуть вниз. */
const EPS = 0.1;

/**
 * Индекс реплики, которая звучит сейчас: последняя, чей start <= currentTime (-1 — нет или выключено).
 * State меняется только при смене реплики, не на каждый timeupdate.
 * audio-элемент появляется асинхронно (плеер грузит части) — подписка переоформляется по `enabled`.
 */
export const useActiveSegment = (
  audioRef: RefObject<HTMLAudioElement | null>,
  starts: number[],
  enabled: boolean,
): number => {
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const audio = audioRef.current;
    if (!enabled || !audio) return;
    const update = () => {
      const time = audio.currentTime + EPS;
      let index = -1;
      let best = -Infinity;
      for (let i = 0; i < starts.length; i += 1) {
        if (starts[i] <= time && starts[i] >= best) {
          best = starts[i];
          index = i;
        }
      }
      setActive((prev) => (prev === index ? prev : index));
    };
    update();
    const events = ['timeupdate', 'seeked', 'loadedmetadata'] as const;
    events.forEach((name) => audio.addEventListener(name, update));
    return () => {
      events.forEach((name) => audio.removeEventListener(name, update));
    };
  }, [audioRef, starts, enabled]);

  return enabled ? active : -1;
};
