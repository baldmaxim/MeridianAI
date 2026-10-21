import { useCallback, useState } from "react";

const STORAGE_KEY = "meridian.meetingSidePanelCollapsed";

const readStored = (): boolean => {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
};

/** Collapsed state of the meeting side panel, remembered between launches. */
export const useSidePanelCollapsed = (): [boolean, () => void] => {
  const [collapsed, setCollapsed] = useState(readStored);

  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        // Storage is unavailable: the state just is not remembered.
      }
      return next;
    });
  }, []);

  return [collapsed, toggle];
};
