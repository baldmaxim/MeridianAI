import { useCallback, useEffect, useRef, useState } from "react";
import { useMeetingStore } from "@/stores/meetingStore";
import {
  toNullable,
  type MeetingContextValue,
} from "@/components/meetings/MeetingContextForm";

export type ContextSaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

const DEBOUNCE_MS = 600;

/**
 * Debounced autosave of the meeting context. Unsaved edits are flushed when
 * the meeting changes or the component unmounts.
 */
export const useContextAutosave = (meetingId: string) => {
  const [status, setStatus] = useState<ContextSaveStatus>({ kind: "idle" });
  const pending = useRef<MeetingContextValue | null>(null);
  const timer = useRef<number | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  const flush = useCallback(async () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    // One request at a time: a newer value waits for the current save.
    if (inFlight.current || pending.current === null) return;
    const value = pending.current;
    pending.current = null;
    inFlight.current = true;
    if (mounted.current) setStatus({ kind: "saving" });
    const error = await useMeetingStore
      .getState()
      .saveContext(
        meetingId,
        toNullable(value.negotiationType),
        toNullable(value.keyTerms),
        toNullable(value.opponentWeaknesses),
      );
    inFlight.current = false;
    if (pending.current !== null) {
      void flush();
      return;
    }
    if (mounted.current) {
      setStatus(
        error === null ? { kind: "saved" } : { kind: "error", message: error },
      );
    }
  }, [meetingId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      void flush();
    };
  }, [flush]);

  const schedule = useCallback(
    (value: MeetingContextValue) => {
      pending.current = value;
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => void flush(), DEBOUNCE_MS);
    },
    [flush],
  );

  return { status, schedule };
};
