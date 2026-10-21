import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import type { UnlistenFn } from "@tauri-apps/api/event";
import { events } from "@/bindings";
import { useMeetingStore } from "@/stores/meetingStore";

/**
 * Subscribes to the meeting events for as long as the app is on screen, loads
 * the list and picks up a meeting that is already being recorded. Returns the
 * id of that meeting once, so the caller can open its screen at startup.
 */
export const useMeetingEvents = (
  enabled: boolean,
  onActiveFound: (meetingId: string) => void,
) => {
  const { t } = useTranslation();
  // Latest values for the long-lived subscriptions below.
  const tRef = useRef(t);
  tRef.current = t;
  const onActiveFoundRef = useRef(onActiveFound);
  onActiveFoundRef.current = onActiveFound;

  useEffect(() => {
    if (!enabled) return;

    let disposed = false;
    const unlisteners: UnlistenFn[] = [];
    const track = (pending: Promise<UnlistenFn>) => {
      pending
        .then((unlisten) => {
          if (disposed) unlisten();
          else unlisteners.push(unlisten);
        })
        .catch((e) => console.warn("Failed to subscribe to meeting event:", e));
    };

    const store = useMeetingStore.getState();
    track(
      events.meetingSegment.listen((e) =>
        store.applySegment(e.payload.segment),
      ),
    );
    track(events.meetingLevels.listen((e) => store.applyLevels(e.payload)));
    track(
      events.meetingVoices.listen((e) =>
        store.applyVoices(e.payload.meeting_id, e.payload.voices),
      ),
    );
    track(
      events.meetingSegmentRemoved.listen((e) =>
        store.applySegmentRemoved(e.payload.meeting_id, e.payload.segment_id),
      ),
    );
    track(
      events.meetingSystemSilent.listen((e) =>
        store.applySystemSilent(e.payload.meeting_id, e.payload.silent),
      ),
    );
    track(
      events.meetingState.listen((e) => {
        store.applyState(e.payload);
        if (e.payload.kind === "recognition_error") {
          toast.error(tRef.current("meetings.errors.recognition"), {
            description: e.payload.message ?? undefined,
          });
        }
      }),
    );

    void (async () => {
      await store.loadList();
      await store.syncActive();
      const active = useMeetingStore.getState().active;
      if (!disposed && active) onActiveFoundRef.current(active.id);
    })();

    return () => {
      disposed = true;
      unlisteners.forEach((unlisten) => unlisten());
    };
  }, [enabled]);
};
