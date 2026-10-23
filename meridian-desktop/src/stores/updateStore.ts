import { create } from "zustand";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import {
  readUpdateMemory,
  UPDATE_DISMISSED_KEY,
  writeUpdateMemory,
} from "@/lib/utils/updateMemory";
import { useMeetingStore } from "./meetingStore";

export type UpdateStatus =
  | "idle"
  | "checking"
  | "available"
  | "installing"
  | "upToDate"
  | "error";

interface UpdateStore {
  status: UpdateStatus;
  /** Найденное обновление; ставится только после согласия пользователя. */
  update: Update | null;
  /** Диалог «Доступна версия X» открыт. */
  dialogOpen: boolean;
  error: string | null;
  /** Когда последняя проверка закончилась (мс); нужно для троттлинга. */
  lastCheckedAt: number;

  /**
   * `silent`: фоновая проверка — без сообщений об ошибке, «обновлений нет»
   * и без сброса уже найденного обновления; диалог сама не открывает повторно.
   */
  checkForUpdates: (silent: boolean) => Promise<void>;
  /** Скачивает, ставит и перезапускает приложение. Во время записи не ставит. */
  installUpdate: () => Promise<void>;
  /** Открывает диалог по просьбе пользователя (плашка, трей). */
  openDialog: () => void;
  /** Автооткрытие: один раз на версию и не во время записи. */
  openDialogIfPending: () => void;
  dismiss: () => void;
}

const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

const isRecording = (): boolean => useMeetingStore.getState().active !== null;

let checkInFlight = false;

export const useUpdateStore = create<UpdateStore>()((set, get) => ({
  status: "idle",
  update: null,
  dialogOpen: false,
  error: null,
  lastCheckedAt: 0,

  checkForUpdates: async (silent) => {
    const { status, update: known } = get();
    if (checkInFlight || status === "installing") return;
    checkInFlight = true;
    // Тихая перепроверка не гасит уже показанный маркер «доступно обновление».
    if (!(silent && status === "available")) {
      set({ status: "checking", error: null });
    }
    try {
      const found = await check();
      if (found) {
        set({ status: "available", update: found, error: null });
        if (silent) get().openDialogIfPending();
        else get().openDialog();
      } else {
        set({ status: "upToDate", update: null, dialogOpen: false });
      }
    } catch (error) {
      console.warn("Update check failed:", error);
      // Найденное обновление не теряем из-за сбоя повторной проверки.
      const restored: UpdateStatus = known ? "available" : "idle";
      set(
        silent
          ? { status: restored }
          : { status: known ? "available" : "error", error: errorText(error) },
      );
    } finally {
      checkInFlight = false;
      set({ lastCheckedAt: Date.now() });
    }
  },

  installUpdate: async () => {
    const { update } = get();
    if (!update || isRecording()) return;
    set({ status: "installing", error: null });
    try {
      await update.downloadAndInstall();
      await relaunch();
    } catch (error) {
      console.warn("Update install failed:", error);
      // Обновление осталось доступным: маркер не пропадает, диалог покажет ошибку.
      set({ status: "available", error: errorText(error), dialogOpen: true });
    }
  },

  openDialog: () => {
    if (get().update) set({ dialogOpen: true });
  },

  openDialogIfPending: () => {
    const { status, update, dialogOpen } = get();
    if (status !== "available" || !update || dialogOpen) return;
    if (readUpdateMemory(UPDATE_DISMISSED_KEY) === update.version) return;
    if (isRecording()) return;
    set({ dialogOpen: true });
  },

  dismiss: () => {
    const { status, update } = get();
    if (status === "installing") return;
    if (update) writeUpdateMemory(UPDATE_DISMISSED_KEY, update.version);
    set({ dialogOpen: false, status: update ? "available" : status });
  },
}));
