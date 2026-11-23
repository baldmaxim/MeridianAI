import { useCallback, useState } from "react";

const STORAGE_KEY = "meridian.meetingSidePanelCollapsed";

const readStored = (key: string, fallback: boolean): boolean => {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value === "1";
  } catch {
    return fallback;
  }
};

/**
 * Collapsed state of a meeting panel, remembered between launches. Until the
 * user has chosen, `defaultCollapsed` decides.
 */
export const useSidePanelCollapsed = (
  storageKey: string = STORAGE_KEY,
  defaultCollapsed = false,
): [boolean, () => void] => {
  const [collapsed, setCollapsed] = useState(() =>
    readStored(storageKey, defaultCollapsed),
  );

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
