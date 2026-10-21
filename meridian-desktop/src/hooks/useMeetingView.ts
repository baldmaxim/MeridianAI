import { useCallback, useEffect, useState } from "react";
import { commands, type MeetingView } from "@/bindings";

export interface MeetingViewState {
  view: MeetingView | null;
  fromCache: boolean;
  loading: boolean;
  /** Neither the server nor the cache answered. */
  error: string | null;
  reload: () => void;
}

/** A meeting of the site (protocol, phrases, documents); cached offline. */
export const useMeetingView = (
  serverMeetingId: number | null,
  enabled = true,
): MeetingViewState => {
  const [view, setView] = useState<MeetingView | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled || serverMeetingId === null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void commands.meetingViewGet(serverMeetingId).then((result) => {
      if (cancelled) return;
      setLoading(false);
      if (result.status === "ok") {
        setView(result.data.view);
        setFromCache(result.data.from_cache);
      } else {
        setError(result.error);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [serverMeetingId, enabled, nonce]);

  // Another meeting: drop the previous one at once.
  useEffect(() => {
    setView(null);
    setError(null);
  }, [serverMeetingId]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { view, fromCache, loading, error, reload };
};
