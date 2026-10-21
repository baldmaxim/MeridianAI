import { useEffect, useState } from "react";
import { commands, type SearchHit } from "@/bindings";

const MIN_QUERY_LENGTH = 2;
const DEBOUNCE_MS = 250;
const RESULT_LIMIT = 30;

export interface MeetingSearchState {
  /** The query is long enough to search. */
  active: boolean;
  hits: SearchHit[];
  loading: boolean;
  error: string | null;
}

const IDLE: MeetingSearchState = {
  active: false,
  hits: [],
  loading: false,
  error: null,
};

/** Debounced full-text search over local and site meetings. */
export const useMeetingSearch = (query: string): MeetingSearchState => {
  const [state, setState] = useState<MeetingSearchState>(IDLE);
  const trimmed = query.trim();

  useEffect(() => {
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setState(IDLE);
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, active: true, loading: true, error: null }));
    const timer = window.setTimeout(() => {
      void commands.searchMeetings(trimmed, RESULT_LIMIT).then((result) => {
        if (cancelled) return;
        setState(
          result.status === "ok"
            ? { active: true, hits: result.data, loading: false, error: null }
            : { active: true, hits: [], loading: false, error: result.error },
        );
      });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [trimmed]);

  return state;
};
