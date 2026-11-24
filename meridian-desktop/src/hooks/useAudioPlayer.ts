import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

type AudioUrlResult =
  | { status: "ok"; data: string | null }
  | { status: "error"; error: string };

export interface IAudioPlayer {
  audioRef: RefObject<HTMLAudioElement>;
  /** The link to play; `null`: no audio (or it could not be played). */
  url: string | null;
  /** Jumps to the second and plays. Stable between renders. */
  seek: (seconds: number) => void;
  /** For the `<audio>` element: the recording is not playable, hide it. */
  handleError: () => void;
}

/**
 * The recording of a meeting or a file: asks the server for the link when
 * `key` changes (a refusal or no connection means "no audio", quietly) and
 * gives the `<audio>` ref with a `seek`. The link is never stored.
 */
export const useAudioPlayer = <K extends string | number>(
  key: K | null,
  load: (key: K) => Promise<AudioUrlResult>,
): IAudioPlayer => {
  const audioRef = useRef<HTMLAudioElement>(null);
  const loadRef = useRef(load);
  loadRef.current = load;
  const [loaded, setLoaded] = useState<{ key: K; url: string } | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);

  useEffect(() => {
    setLoaded(null);
    if (key === null) return;
    let cancelled = false;
    loadRef
      .current(key)
      .then((result) => {
        if (cancelled || result.status !== "ok" || !result.data) return;
        setLoaded({ key, url: result.data });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [key]);

  const url =
    loaded && loaded.key === key && loaded.url !== failedUrl
      ? loaded.url
      : null;

  const handleError = useCallback(() => {
    setFailedUrl(loaded?.url ?? null);
  }, [loaded]);

  const seek = useCallback((seconds: number) => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(seconds)) return;
    const go = () => {
      audio.currentTime = Math.max(0, seconds);
      void audio.play().catch(() => undefined);
    };
    if (audio.readyState >= 1) go();
    else audio.addEventListener("loadedmetadata", go, { once: true });
  }, []);

  return { audioRef, url, seek, handleError };
};

/** A click that ends a text selection inside `row` must not move the recording. */
export const hasTextSelection = (row: Node): boolean => {
  const selection = window.getSelection();
  return (
    !!selection &&
    !selection.isCollapsed &&
    selection.toString() !== "" &&
    !!selection.anchorNode &&
    row.contains(selection.anchorNode)
  );
};

/**
 * The phrase being played: the last one that started at or before the current
 * time (phrases without a start are skipped). The state changes only when the
 * phrase does, not on every `timeupdate`. While playing, the phrase is scrolled
 * into view (`rowRefs[index]`).
 */
export const useActiveSegment = (
  player: IAudioPlayer,
  starts: ReadonlyArray<number | null>,
) => {
  const [active, setActive] = useState(-1);
  const rowRefs = useRef<Array<HTMLElement | null>>([]);
  const { audioRef, url } = player;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !url) {
      setActive(-1);
      return;
    }
    const update = () => {
      const time = audio.currentTime;
      let index = -1;
      let best = -1;
      for (let i = 0; i < starts.length; i += 1) {
        const start = starts[i];
        if (start !== null && start <= time && start >= best) {
          best = start;
          index = i;
        }
      }
      setActive(index);
    };
    update();
    const events = ["timeupdate", "seeked", "loadedmetadata"] as const;
    events.forEach((name) => audio.addEventListener(name, update));
    return () => {
      events.forEach((name) => audio.removeEventListener(name, update));
    };
  }, [audioRef, url, starts]);

  useEffect(() => {
    const audio = audioRef.current;
    if (active < 0 || !audio || audio.paused) return;
    rowRefs.current[active]?.scrollIntoView({ block: "nearest" });
  }, [active, audioRef]);

  return { active, rowRefs };
};
