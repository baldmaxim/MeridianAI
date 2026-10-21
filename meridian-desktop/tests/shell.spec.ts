import { test, expect, type Page } from "@playwright/test";

/**
 * Smoke tests of the window frame (icon rail, header, settings screen,
 * recording pill) with a mocked Tauri bridge.
 */

interface MockOptions {
  recording: boolean;
  signedIn: boolean;
}

const MEETING = {
  id: "m-live",
  title: "Планёрка по объекту",
  capture_mode: "online",
  started_at: "2026-10-21T09:00:00.000Z",
  ended_at: null,
  status: "recording",
  duration_seconds: 0,
  server_meeting_id: null,
  sync_state: "pending",
  sync_error: null,
  synced_at: null,
  customer_id: null,
  object_id: null,
  audio_state: "pending",
  web_url: null,
};

const installTauriMock = async (page: Page, options: MockOptions) => {
  await page.addInitScript(
    ({ meeting, opts }) => {
      type Handler = (payload: unknown) => void;
      const callbacks = new Map<number, Handler>();
      const listeners = new Map<string, number[]>();
      let nextId = 1;
      const w = window as unknown as Record<string, unknown>;
      const calls: string[] = [];
      w.__calls = calls;
      const settings = {
        onboarding_completed: true,
        selected_model: "gigaam",
        theme: "dark",
        accent_color: "amber",
        debug_mode: false,
        post_process_enabled: false,
        server_url: "https://meridianai.ru",
        upload_audio: true,
      };
      const account = {
        server_url: "https://meridianai.ru",
        user: { id: 1, email: "boss@example.com", display_name: "Иван Петров" },
        device_id: 3,
        logged_in: true,
      };
      const answer = (cmd: string): unknown => {
        calls.push(cmd);
        switch (cmd) {
          case "get_app_settings":
            return settings;
          case "get_retired_models":
          case "get_available_models":
          case "get_available_microphones":
          case "get_available_output_devices":
            return [];
          case "get_current_model":
            return "gigaam";
          case "list_meetings":
            return [meeting];
          case "get_active_meeting":
            return opts.recording
              ? {
                  meeting,
                  elapsed_seconds: 125,
                  queue_len: 0,
                  levels: { mic: 0.45, system: 0.2 },
                }
              : null;
          case "get_meeting":
            return { meeting, segments: [], notes: [] };
          case "stop_meeting":
            return { ...meeting, status: "stopped", ended_at: "x" };
          case "get_account":
            return opts.signedIn ? account : null;
          case "get_sync_status":
            return {
              online: true,
              running: false,
              pending_count: 0,
              last_error: null,
              last_sync_at: null,
              syncing_meeting_id: null,
            };
          case "plugin:event|listen":
            return 1;
          default:
            return null;
        }
      };
      w.__TAURI_OS_PLUGIN_INTERNALS__ = {
        platform: "linux",
        eol: "\n",
        version: "0",
        family: "unix",
        os_type: "linux",
        arch: "x86_64",
        exe_extension: "",
      };
      w.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener: () => {} };
      w.__TAURI_INTERNALS__ = {
        metadata: {
          currentWindow: { label: "main" },
          currentWebview: { label: "main", windowLabel: "main" },
        },
        transformCallback: (cb: Handler) => {
          const id = nextId++;
          callbacks.set(id, cb);
          return id;
        },
        unregisterCallback: (id: number) => callbacks.delete(id),
        convertFileSrc: (p: string) => p,
        invoke: async (cmd: string, args?: Record<string, unknown>) => {
          if (cmd === "plugin:event|listen" && args) {
            const name = String(args.event);
            const handlers = listeners.get(name) ?? [];
            handlers.push(Number(args.handler));
            listeners.set(name, handlers);
            return Number(args.handler);
          }
          return answer(cmd);
        },
      };
    },
    { meeting: MEETING, opts: options },
  );
};

const calls = (page: Page) =>
  page.evaluate(() => (window as unknown as { __calls: string[] }).__calls);

test.describe("Window frame (mocked Tauri)", () => {
  test.use({ viewport: { width: 800, height: 600 } });

  test("gear opens settings with pill tabs, no horizontal scroll at 800px", async ({
    page,
  }) => {
    await installTauriMock(page, { recording: false, signedIn: true });
    await page.goto("/");
    await expect(page.getByText("Планёрка по объекту")).toBeVisible();
    await page.getByRole("button", { name: "Настройки", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Настройки" }),
    ).toBeVisible();
    for (const name of ["Аккаунт", "Общие", "Модели", "Дополнительно"]) {
      await expect(page.getByRole("tab", { name })).toBeVisible();
    }
    await expect(page.getByRole("tab", { name: "Отладка" })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Постобработка" })).toHaveCount(
      0,
    );
    await page.getByRole("tab", { name: "О программе" }).click();
    await expect(page.getByText("Версия").first()).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.getByRole("button", { name: "Встречи", exact: true }).click();
    await expect(page.getByText("Планёрка по объекту")).toBeVisible();
  });

  test("account circle shows initials and opens the account tab", async ({
    page,
  }) => {
    await installTauriMock(page, { recording: false, signedIn: true });
    await page.goto("/");
    const circle = page.getByRole("button", { name: /^Аккаунт: / });
    await expect(circle).toHaveText("ИП");
    await circle.click();
    await expect(page.getByRole("tab", { name: "Аккаунт" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("recording pill is visible in settings, opens the meeting and stops it", async ({
    page,
  }) => {
    await installTauriMock(page, { recording: true, signedIn: true });
    await page.goto("/");
    const pill = page.getByRole("button", { name: /Открыть идущую встречу/ });
    await expect(pill).toBeVisible();
    await expect(pill).toContainText("02:05");
    await page.getByRole("button", { name: "Настройки", exact: true }).click();
    await expect(pill).toBeVisible();
    await pill.click();
    await expect(
      page.getByRole("button", { name: "К списку встреч" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Остановить", exact: true })
      .first()
      .click();
    await expect.poll(() => calls(page)).toContain("stop_meeting");
  });
});
