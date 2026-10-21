import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import type { UnlistenFn } from "@tauri-apps/api/event";
import { events } from "@/bindings";
import { useMeetingStore } from "@/stores/meetingStore";
import { useSyncStore } from "@/stores/syncStore";

/** Pause that merges a burst of sync events into one reload. */
const RELOAD_DELAY_MS = 200;

/**
 * Keeps the account and the upload status up to date and refreshes the
 * meetings whose upload state changed, so the badges follow without a restart.
 */
export const useSyncEvents = (enabled: boolean) => {
  const { t } = useTranslation();
  const tRef = useRef(t);
  tRef.current = t;

  useEffect(() => {
    if (!enabled) return;

    let disposed = false;
    let reloadTimer: number | undefined;
    const unlisteners: UnlistenFn[] = [];
    const track = (pending: Promise<UnlistenFn>) => {
      pending
        .then((unlisten) => {
          if (disposed) unlisten();
          else unlisteners.push(unlisten);
        })
        .catch((e) => console.warn("Failed to subscribe to sync event:", e));
    };

    const scheduleReload = (touchedId: string | null) => {
      window.clearTimeout(reloadTimer);
      reloadTimer = window.setTimeout(() => {
        const meetings = useMeetingStore.getState();
        void meetings.loadList();
        if (touchedId && meetings.openId === touchedId) {
          void meetings.openMeeting(touchedId);
        }
      }, RELOAD_DELAY_MS);
    };

    const sync = useSyncStore.getState();
    track(
      events.syncState.listen((e) => {
        sync.setStatus(e.payload.status);
        if (e.payload.meeting_id) scheduleReload(e.payload.meeting_id);
      }),
    );
    track(
      events.accountChanged.listen((e) => {
        sync.setAccount(e.payload.account);
        if (e.payload.reason) {
          toast.error(tRef.current("account.signedOut"), {
            description: e.payload.reason,
          });
        }
        // The links to the site depend on the account.
        scheduleReload(useMeetingStore.getState().openId);
      }),
    );
    void sync
      .load()
      .catch((e) => console.warn("Failed to load the sync status:", e));

    return () => {
      disposed = true;
      window.clearTimeout(reloadTimer);
      unlisteners.forEach((unlisten) => unlisten());
    };
  }, [enabled]);
};
