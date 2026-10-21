import { create } from "zustand";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

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

  /** `silent`: на старте, без сообщений об ошибке и «обновлений нет». */
  checkForUpdates: (silent: boolean) => Promise<void>;
  /** Скачивает, ставит и перезапускает приложение. */
  installUpdate: () => Promise<void>;
  dismiss: () => void;
}

const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

export const useUpdateStore = create<UpdateStore>()((set, get) => ({
  status: "idle",
  update: null,
  dialogOpen: false,
  error: null,

  checkForUpdates: async (silent) => {
    const { status } = get();
    if (status === "checking" || status === "installing") return;
    set({ status: "checking", error: null });
    try {
      const update = await check();
      if (update) {
        set({ status: "available", update, dialogOpen: true });
      } else {
        set({ status: "upToDate", update: null });
      }
    } catch (error) {
      console.warn("Update check failed:", error);
      set(
        silent
          ? { status: "idle" }
          : { status: "error", error: errorText(error) },
      );
    }
  },

  installUpdate: async () => {
    const { update } = get();
    if (!update) return;
    set({ status: "installing", error: null });
    try {
      await update.downloadAndInstall();
      await relaunch();
    } catch (error) {
      console.warn("Update install failed:", error);
      set({ status: "error", error: errorText(error), dialogOpen: false });
    }
  },

  dismiss: () => {
    if (get().status === "installing") return;
    set({ dialogOpen: false, status: "available" });
  },
}));
