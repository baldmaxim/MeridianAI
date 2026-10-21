import { useEffect, useState } from 'react';

/** Текущее время (мс), обновляется раз в intervalMs — чтобы не вызывать Date.now() в render. */
export const useNow = (intervalMs = 5000): number => {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
};
