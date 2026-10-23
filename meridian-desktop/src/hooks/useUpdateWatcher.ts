import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { commands } from "@/bindings";
import { notifyUpdateIfHidden } from "@/lib/utils/updateNotification";
import { useMeetingStore } from "@/stores/meetingStore";
import { useUpdateStore } from "@/stores/updateStore";

/** Первая проверка после запуска. */
const STARTUP_DELAY_MS = 5000;
/** Периодическая проверка. */
const CHECK_PERIOD_MS = 4 * 60 * 60 * 1000;
/** Проверки (кроме стартовой) не чаще, чем раз в это время. */
const MIN_CHECK_GAP_MS = 30 * 60 * 1000;
/** Трей просит показать диалог обновления (см. `UPDATE_OPEN_EVENT` в lib.rs). */
const UPDATE_OPEN_EVENT = "update-open-requested";

/**
 * Следит за обновлениями: проверка на старте, раз в 4 часа и при фокусе окна;
 * системное уведомление, если окно не на виду; версия в меню трея; диалог
 * после остановки записи. Монтируется один раз.
 */
export const useUpdateWatcher = (enabled: boolean) => {
  const { t } = useTranslation();
  const tRef = useRef(t);
  tRef.current = t;

  // Проверки.
  useEffect(() => {
    if (!enabled) return;

    const run = async (force: boolean) => {
      const store = useUpdateStore.getState();
      if (!force && Date.now() - store.lastCheckedAt < MIN_CHECK_GAP_MS) return;
      await store.checkForUpdates(true);
      const { status, update } = useUpdateStore.getState();
      if (status !== "available" || !update) return;
      await notifyUpdateIfHidden(
        update.version,
        tRef.current("update.notification.title"),
        tRef.current("update.notification.body", { version: update.version }),
      );
    };

    const startupTimer = window.setTimeout(
      () => void run(true),
      STARTUP_DELAY_MS,
    );
    const periodTimer = window.setInterval(
      () => void run(false),
      CHECK_PERIOD_MS,
    );

    let disposed = false;
    let unlistenFocus: (() => void) | undefined;
    void getCurrentWindow()
      .onFocusChanged(({ payload: focused }) => {
        if (focused) void run(false);
      })
      .then((unlisten) => {
        if (disposed) unlisten();
        else unlistenFocus = unlisten;
      });

    return () => {
      disposed = true;
      window.clearTimeout(startupTimer);
      window.clearInterval(periodTimer);
      unlistenFocus?.();
    };
  }, [enabled]);

  // Версия обновления — в меню трея («Установить обновление X»).
  useEffect(() => {
    if (!enabled) return;
    let reported: string | null = null;
    const sync = (state: ReturnType<typeof useUpdateStore.getState>) => {
      const pending =
        state.update &&
        (state.status === "available" || state.status === "installing")
          ? state.update.version
          : null;
      if (pending === reported) return;
      reported = pending;
      void commands.setUpdateAvailable(pending);
    };
    sync(useUpdateStore.getState());
    return useUpdateStore.subscribe(sync);
  }, [enabled]);

  // Клик по пункту трея открывает диалог.
  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void listen(UPDATE_OPEN_EVENT, () =>
      useUpdateStore.getState().openDialog(),
    ).then((fn) => {
      if (disposed) fn();
      else unlisten = fn;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [enabled]);

  // Запись закончилась: если диалог ждал, открываем его.
  useEffect(() => {
    if (!enabled) return;
    return useMeetingStore.subscribe((state, prev) => {
      if (prev.active && !state.active) {
        useUpdateStore.getState().openDialogIfPending();
      }
    });
  }, [enabled]);
};
