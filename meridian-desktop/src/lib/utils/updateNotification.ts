import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import {
  readUpdateMemory,
  UPDATE_NOTIFIED_KEY,
  writeUpdateMemory,
} from "./updateMemory";

/** Окно на виду у пользователя: видно, не свёрнуто и в фокусе. */
const isWindowInFront = async (): Promise<boolean> => {
  const win = getCurrentWindow();
  const [focused, visible, minimized] = await Promise.all([
    win.isFocused(),
    win.isVisible(),
    win.isMinimized(),
  ]);
  return focused && visible && !minimized;
};

/**
 * Одно системное уведомление на версию, и только если окно не на виду.
 * Разрешение просим здесь же; отказ или сбой — молча пропускаем.
 */
export const notifyUpdateIfHidden = async (
  version: string,
  title: string,
  body: string,
): Promise<void> => {
  if (readUpdateMemory(UPDATE_NOTIFIED_KEY) === version) return;
  try {
    if (await isWindowInFront()) return;
    // Помечаем до запроса разрешения, чтобы не спрашивать каждые 4 часа.
    writeUpdateMemory(UPDATE_NOTIFIED_KEY, version);
    const granted =
      (await isPermissionGranted()) ||
      (await requestPermission()) === "granted";
    if (!granted) return;
    sendNotification({ title, body });
  } catch (error) {
    console.warn("Update notification failed:", error);
  }
};
