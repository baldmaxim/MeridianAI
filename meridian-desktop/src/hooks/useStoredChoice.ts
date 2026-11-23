import { useCallback, useState } from "react";

/** A choice among `allowed` values, remembered in localStorage under `key`. */
export const useStoredChoice = <T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): [T, (value: T) => void] => {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return allowed.find((item) => item === stored) ?? fallback;
    } catch {
      return fallback;
    }
  });

  const choose = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // Storage is unavailable: the choice just is not remembered.
      }
    },
    [key],
  );

  return [value, choose];
};
