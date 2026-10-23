import { useCallback, useState } from "react";

const STORAGE_KEY = "meridian.meetingSidePanelCollapsed";

const readStored = (key: string): boolean => {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
};

/** Collapsed state of a meeting panel, remembered between launches. */
export const useSidePanelCollapsed = (
  storageKey: string = STORAGE_KEY,
): [boolean, () => void] => {
  const [collapsed, setCollapsed] = useState(() => readStored(storageKey));

  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(storageKey, next ? "1" : "0");
      } catch {
        // Storage is unavailable: the state just is not remembered.
      }
      return next;
    });
  }, [storageKey]);

  return [collapsed, toggle];
};
