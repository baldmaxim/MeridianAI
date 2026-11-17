import { commands, type Theme } from "@/bindings";

/**
 * Appearance theme handling.
 *
 * Meridian ships a full light palette and a full dark palette (see
 * `styles/theme.css`). The user picks which one is used:
 *  - `light` / `dark` set `data-theme` on the document root explicitly.
 *  - `system` sets `data-theme` to the OS scheme (`matchMedia`) and follows
 *    its changes while `system` stays selected.
 *
 * `data-theme` is therefore always present once JS runs; the
 * `prefers-color-scheme` CSS branch is only a fallback until then.
 *
 * The user's choice (system|light|dark, not the effective theme) is persisted
 * in `AppSettings` (source of truth) and mirrored to localStorage so it can be
 * applied synchronously on boot, before React mounts, avoiding a flash of the
 * wrong palette.
 */

export const THEME_STORAGE_KEY = "meridian.theme";

export const THEME_OPTIONS: Theme[] = ["system", "light", "dark"];

const isTheme = (value: unknown): value is Theme =>
  value === "system" || value === "light" || value === "dark";

const DARK_QUERY = "(prefers-color-scheme: dark)";

let systemQuery: MediaQueryList | null = null;
let systemListener: (() => void) | null = null;

const stopFollowingSystem = (): void => {
  if (systemQuery && systemListener) {
    systemQuery.removeEventListener("change", systemListener);
  }
  systemQuery = null;
  systemListener = null;
};

/** The theme actually shown right now (`data-theme` on the root). */
export const getEffectiveTheme = (): "light" | "dark" =>
  document.documentElement.dataset.theme === "light" ? "light" : "dark";

/** Apply a theme to the document root and remember it for the next launch. */
export const applyTheme = (theme: Theme): void => {
  const root = document.documentElement;
  stopFollowingSystem();
  if (theme === "system") {
    const query = window.matchMedia(DARK_QUERY);
    const listener = () => {
      root.dataset.theme = query.matches ? "dark" : "light";
    };
    listener();
    query.addEventListener("change", listener);
    systemQuery = query;
    systemListener = listener;
  } else {
    root.dataset.theme = theme;
  }
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // localStorage may be unavailable (e.g. private mode); the setting still
    // persists in AppSettings, so this only costs a one-frame flash on boot.
  }
};

/** Read the last-applied theme for synchronous boot-time application.
 * Fallback matches `default_theme()` in src-tauri/src/settings.rs. */
export const getStoredTheme = (): Theme => {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (isTheme(stored)) return stored;
  } catch {
    // ignore
  }
  return "dark";
};

/** Apply the persisted theme from AppSettings (the source of truth). */
export const syncThemeFromSettings = async (): Promise<void> => {
  try {
    const result = await commands.getAppSettings();
    if (result.status === "ok") {
      applyTheme(result.data.theme ?? "dark");
    }
  } catch (e) {
    console.warn("Failed to sync theme from settings:", e);
  }
};
