import { useEffect, useState } from "react";

/** Seconds since `since` (ms epoch), refreshed twice a second; 0 when null. */
export const useElapsedSeconds = (since: number | null): number => {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (since === null) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [since]);

  return since === null ? 0 : Math.max(0, (now - since) / 1000);
};
