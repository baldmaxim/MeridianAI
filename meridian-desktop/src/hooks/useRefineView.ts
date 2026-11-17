import { useEffect } from "react";
import { useMeetingView, type MeetingViewState } from "@/hooks/useMeetingView";

/** The server is re-transcribing: the view is polled while it lasts. */
export const isRefineActive = (status: string | null | undefined): boolean =>
  status === "pending" || status === "running";

export const REFINE_POLL_MS = 20_000;

/**
 * The view of a synced meeting with polling while the server re-transcribes it
 * (`pending`/`running`). Every poll goes to the server (the offline cache is
 * only a fallback), and stops on a final status or on unmount.
 */
export const useRefineView = (
  serverMeetingId: number | null,
  syncState: string,
): MeetingViewState => {
  const state = useMeetingView(serverMeetingId, true, syncState);
  const active = isRefineActive(state.view?.refine_status);
  const { reload } = state;

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(reload, REFINE_POLL_MS);
    return () => clearInterval(timer);
  }, [active, reload]);

  return state;
};
