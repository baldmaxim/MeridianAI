import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "meridian.meetingSidePanelWidth";

export const SIDE_PANEL_MIN_WIDTH = 300;
export const SIDE_PANEL_DEFAULT_WIDTH = 400;
/** The panel never takes more than this share of the window. */
const MAX_WINDOW_SHARE = 0.7;

/** The widest the panel may be in a window `windowWidth` wide (never below the minimum). */
export const sidePanelMaxWidth = (windowWidth: number): number =>
  Math.max(SIDE_PANEL_MIN_WIDTH, Math.floor(windowWidth * MAX_WINDOW_SHARE));

export const clampSidePanelWidth = (
  width: number,
  windowWidth: number,
): number =>
  Math.min(
    Math.max(Math.round(width), SIDE_PANEL_MIN_WIDTH),
    sidePanelMaxWidth(windowWidth),
  );

const readStored = (key: string): number => {
  try {
    const value = Number(window.localStorage.getItem(key));
    return Number.isFinite(value) && value > 0
      ? value
      : SIDE_PANEL_DEFAULT_WIDTH;
  } catch {
    return SIDE_PANEL_DEFAULT_WIDTH;
  }
};

export interface SidePanelWidth {
  /** The width to show: the chosen one, kept inside the current window. */
  width: number;
  maxWidth: number;
  setWidth: (width: number) => void;
  reset: () => void;
}

/** Width of the right panel of a meeting, remembered between launches. */
export const useSidePanelWidth = (
  storageKey: string = STORAGE_KEY,
): SidePanelWidth => {
  const [stored, setStored] = useState(() => readStored(storageKey));
  const [windowWidth, setWindowWidth] = useState(() => window.innerWidth);

  // A smaller window pulls the panel in; a bigger one gives the chosen width back.
  useEffect(() => {
    const onResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const persist = useCallback(
    (value: number) => {
      try {
        window.localStorage.setItem(storageKey, String(value));
      } catch {
        // Storage is unavailable: the width just is not remembered.
      }
    },
    [storageKey],
  );

  const setWidth = useCallback(
    (next: number) => {
      const value = clampSidePanelWidth(next, window.innerWidth);
      setStored(value);
      persist(value);
    },
    [persist],
  );

  const reset = useCallback(() => {
    setStored(SIDE_PANEL_DEFAULT_WIDTH);
    persist(SIDE_PANEL_DEFAULT_WIDTH);
  }, [persist]);

  return {
    width: clampSidePanelWidth(stored, windowWidth),
    maxWidth: sidePanelMaxWidth(windowWidth),
    setWidth,
    reset,
  };
};
