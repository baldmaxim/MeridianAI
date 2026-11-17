import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { open } from "@tauri-apps/plugin-dialog";
import type { UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { commands, events, type TranscriptionItem } from "@/bindings";

/** File types the server takes for a transcription (the app checks them again). */
const AUDIO_EXTENSIONS = ["mp3", "wav", "m4a", "ogg", "flac", "opus", "webm"];

export interface Transcriptions {
  /** `null` until the first load. */
  items: TranscriptionItem[] | null;
  /** Files are being dragged over the window. */
  dragActive: boolean;
  pickFiles: () => Promise<void>;
  remove: (id: string) => Promise<void>;
}

/**
 * The list of «Расшифровка файлов»: reloaded on every `transcriptions-changed`;
 * files dropped onto the window while the screen is open are queued.
 */
export const useTranscriptions = (): Transcriptions => {
  const { t } = useTranslation();
  const [items, setItems] = useState<TranscriptionItem[] | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const requestId = useRef(0);
  const tRef = useRef(t);
  tRef.current = t;

  const refresh = useCallback(async () => {
    const id = ++requestId.current;
    const result = await commands.transcriptionsList();
    if (id !== requestId.current) return;
    if (result.status === "ok") setItems(result.data);
    else console.warn("Failed to load the transcriptions:", result.error);
  }, []);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    let disposed = false;
    let unlisten: UnlistenFn | undefined;
    events.transcriptionsChanged
      .listen(() => void refreshRef.current())
      .then((fn) => {
        if (disposed) fn();
        else unlisten = fn;
      })
      .catch((e) =>
        console.warn("Failed to subscribe to transcription events:", e),
      );
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  const addPaths = useCallback(async (paths: string[]) => {
    if (paths.length === 0) return;
    const result = await commands.transcriptionsAdd(paths);
    if (result.status === "error") {
      toast.error(tRef.current("transcriptions.addFailed"), {
        description: result.error,
      });
    }
    await refreshRef.current();
  }, []);
  const addPathsRef = useRef(addPaths);
  addPathsRef.current = addPaths;

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
          name: tRef.current("transcriptions.dialogFilter"),
          extensions: AUDIO_EXTENSIONS,
        },
      ],
    });
    if (chosen === null) return;
    await addPathsRef.current(Array.isArray(chosen) ? chosen : [chosen]);
  }, []);

  const remove = useCallback(async (id: string) => {
    const result = await commands.transcriptionsRemove(id);
    if (result.status === "error") {
      toast.error(tRef.current("transcriptions.removeFailed"), {
        description: result.error,
      });
    }
    await refreshRef.current();
  }, []);

  return { items, dragActive, pickFiles, remove };
};
