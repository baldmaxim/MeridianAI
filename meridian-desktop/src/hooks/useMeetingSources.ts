import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { open } from "@tauri-apps/plugin-dialog";
import type { UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import {
  commands,
  events,
  type MeetingDocuments,
  type RejectedDocument,
  type ServerDocument,
} from "@/bindings";

/** Between two refreshes while something is still being uploaded or read. */
const POLL_INTERVAL_MS = 5000;
/** How long the list of refused files stays on screen. */
const REJECTED_SHOWN_MS = 8000;
/** File types the server takes as sources (the app checks them again). */
const FILE_EXTENSIONS = ["pdf", "docx", "xlsx", "txt", "md", "csv"];

/** The server has finished reading the document (or failed to). */
export const isSettled = (doc: ServerDocument): boolean =>
  doc.status === "ready" || doc.status === "error";

interface MeetingSourcesArgs {
  /** The local meeting; `null` for a meeting of the site. */
  meetingId: string | null;
  serverMeetingId: number | null;
}

export interface MeetingSources {
  data: MeetingDocuments | null;
  /** Files of the last drop or choice that the app refused. */
  rejected: RejectedDocument[];
  /** Files are being dragged over the window. */
  dragActive: boolean;
  pickFiles: () => Promise<void>;
  setIncluded: (doc: ServerDocument, included: boolean) => Promise<void>;
  removeQueued: (queueId: number) => Promise<void>;
}

/**
 * Sources of a meeting: the files waiting for the server and the server's own
 * list. Files dropped onto the window while the screen is open are queued.
 */
export const useMeetingSources = ({
  meetingId,
  serverMeetingId,
}: MeetingSourcesArgs): MeetingSources => {
  const { t } = useTranslation();
  const [data, setData] = useState<MeetingDocuments | null>(null);
  const [rejected, setRejected] = useState<RejectedDocument[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const requestId = useRef(0);
  const rejectedTimer = useRef<number | undefined>(undefined);
  const tRef = useRef(t);
  tRef.current = t;

  const refresh = useCallback(async () => {
    const id = ++requestId.current;
    const result = await commands.meetingDocumentsList(
      meetingId,
      serverMeetingId,
    );
    if (id !== requestId.current) return;
    if (result.status === "ok") setData(result.data);
    else console.warn("Failed to load the meeting sources:", result.error);
  }, [meetingId, serverMeetingId]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  // Another meeting: drop the previous one's list at once.
  const meetingKey = meetingId ?? `server-${serverMeetingId}`;
  useEffect(() => {
    requestId.current++;
    setData(null);
    setRejected([]);
  }, [meetingKey]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The sync reports every pass: a finished upload shows up without polling.
  useEffect(() => {
    let disposed = false;
    let unlisten: UnlistenFn | undefined;
    events.syncState
      .listen(() => void refreshRef.current())
      .then((fn) => {
        if (disposed) fn();
        else unlisten = fn;
      })
      .catch((e) => console.warn("Failed to subscribe to sync event:", e));
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  const needsPolling =
    data !== null &&
    (data.queued.some((item) => item.state !== "error") ||
      (data.server ?? []).some((doc) => !isSettled(doc)));
  useEffect(() => {
    if (!needsPolling) return;
    const timer = window.setInterval(
      () => void refreshRef.current(),
      POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [needsPolling]);

  const addPaths = useCallback(
    async (paths: string[]) => {
      if (paths.length === 0) return;
      const result = await commands.meetingDocumentsAdd(
        meetingId,
        serverMeetingId,
        paths,
      );
      if (result.status === "ok") {
        window.clearTimeout(rejectedTimer.current);
        setRejected(result.data.rejected);
        if (result.data.rejected.length > 0) {
          rejectedTimer.current = window.setTimeout(
            () => setRejected([]),
            REJECTED_SHOWN_MS,
          );
        }
      } else {
        toast.error(tRef.current("meetings.sources.addFailed"), {
          description: result.error,
        });
      }
      await refreshRef.current();
    },
    [meetingId, serverMeetingId],
  );
  const addPathsRef = useRef(addPaths);
  addPathsRef.current = addPaths;

  useEffect(() => () => window.clearTimeout(rejectedTimer.current), []);

  // Files dragged from the file manager onto the window (Tauri reports them
  // with their paths; the browser's own drop events carry no paths).
  useEffect(() => {
    let disposed = false;
    let unlisten: UnlistenFn | undefined;
    getCurrentWebview()
      .onDragDropEvent((event) => {
        const payload = event.payload;
        if (payload.type === "enter" || payload.type === "over") {
          setDragActive(true);
        } else if (payload.type === "leave") {
          setDragActive(false);
        } else {
          setDragActive(false);
          void addPathsRef.current(payload.paths);
        }
      })
      .then((fn) => {
        if (disposed) fn();
        else unlisten = fn;
      })
      .catch((e) => console.warn("Failed to subscribe to file drops:", e));
    return () => {
      disposed = true;
      unlisten?.();
      setDragActive(false);
    };
  }, []);

  const pickFiles = useCallback(async () => {
    const chosen = await open({
      multiple: true,
      directory: false,
      filters: [
        {
          name: tRef.current("meetings.sources.dialogFilter"),
          extensions: FILE_EXTENSIONS,
        },
      ],
    });
    if (chosen === null) return;
    await addPathsRef.current(Array.isArray(chosen) ? chosen : [chosen]);
  }, []);

  const setIncluded = useCallback(
    async (doc: ServerDocument, included: boolean) => {
      if (serverMeetingId === null) return;
      setData((current) =>
        current && current.server
          ? {
              ...current,
              server: current.server.map((item) =>
                item.document_id === doc.document_id
                  ? { ...item, included }
                  : item,
              ),
            }
          : current,
      );
      const result = await commands.meetingDocumentSetIncluded(
        serverMeetingId,
        doc.document_id,
        included,
      );
      if (result.status === "error") {
        toast.error(tRef.current("meetings.sources.includeFailed"), {
          description: result.error,
        });
      }
      // On success this just confirms; on failure it brings the old value back.
      await refreshRef.current();
    },
    [serverMeetingId],
  );

  const removeQueued = useCallback(async (queueId: number) => {
    const result = await commands.meetingDocumentRemoveQueued(queueId);
    if (result.status === "error") {
      toast.error(tRef.current("meetings.sources.removeFailed"), {
        description: result.error,
      });
    }
    await refreshRef.current();
  }, []);

  return { data, rejected, dragActive, pickFiles, setIncluded, removeQueued };
};
