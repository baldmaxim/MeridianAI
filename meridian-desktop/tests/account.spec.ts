import { test, expect, type Page } from "@playwright/test";

/**
 * Smoke tests of the account, the upload status and the sync badges with a
 * mocked Tauri bridge (same approach as tests/meetings.spec.ts).
 */

interface MockOptions {
  signedIn: boolean;
  pending: number;
}

const BASE_MEETING = {
  capture_mode: "in_person",
  ended_at: "2026-10-20T09:10:05.000Z",
  status: "stopped",
  duration_seconds: 605,
  server_meeting_id: null,
  sync_error: null,
  synced_at: null,
  customer_id: null,
  object_id: null,
  audio_state: "pending",
  web_url: null,
};

const MEETINGS = [
  {
    ...BASE_MEETING,
    id: "m-broken",
    title: "Отказ сервера",
    started_at: "2026-10-21T09:00:00.000Z",
    sync_state: "error",
    sync_error: "Сервер отказал: слишком большой файл",
  },
  {
    ...BASE_MEETING,
    id: "m-done",
    title: "Отправленная встреча",
    started_at: "2026-10-20T09:00:00.000Z",
    sync_state: "synced",
    server_meeting_id: 7,
    web_url: "https://meridianai.ru/meetings/7",
    audio_state: "no_storage",
  },
  {
    ...BASE_MEETING,
    id: "m-empty",
    title: "Пустая запись",
    started_at: "2026-10-19T09:00:00.000Z",
    sync_state: "empty",
  },
];

const installTauriMock = async (page: Page, options: MockOptions) => {
  await page.addInitScript(
    ({ meetings, opts }) => {
      type Handler = (payload: unknown) => void;
      const callbacks = new Map<number, Handler>();
      const listeners = new Map<string, number[]>();
      let nextId = 1;
      const w = window as unknown as Record<string, unknown>;
      const calls: string[] = [];
      w.__calls = calls;
      const list = meetings.map((m) => ({ ...m }));
      const account = {
        server_url: "https://meridianai.ru",
        user: { id: 1, email: "boss@example.com", display_name: null },
        device_id: 3,
        logged_in: true,
      };
      let current: typeof account | null = opts.signedIn ? account : null;
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
      const status = () => ({
        online: true,
        running: false,
        pending_count: opts.pending,
        last_error: null,
        last_sync_at: null,
        syncing_meeting_id: null,
      });
      const answer = (cmd: string, args?: Record<string, unknown>): unknown => {
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
            return list;
          case "get_active_meeting":
            return null;
          case "get_meeting":
            return {
              meeting: list.find((m) => m.id === args?.id) ?? list[0],
              segments: [],
              notes: [],
            };
          case "library_get":
            return {
              items: [],
              projects: [],
              fetched_at: null,
              offline: false,
              signed_in: current !== null,
            };
          case "get_account":
            return current;
          case "get_sync_status":
            return status();
          case "account_login": {
            const request = args?.request as { password: string };
            if (request.password !== "right") {
              throw "Неверный логин или пароль";
            }
            current = account;
            return account;
          }
          case "account_logout":
            current = null;
            return null;
          case "retry_meeting_sync": {
            const meeting = list.find((m) => m.id === args?.id);
            if (meeting) {
              meeting.sync_state = "pending";
              meeting.sync_error = null;
            }
            return null;
          }
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
          return answer(cmd, args);
        },
      };
      w.__emit = (event: string, payload: unknown) => {
        for (const id of listeners.get(event) ?? []) {
          callbacks.get(id)?.({ event, id, payload });
        }
      };
    },
    { meetings: MEETINGS, opts: options },
  );
};

const emit = (page: Page, event: string, payload: unknown) =>
  page.evaluate(
    ([name, data]) =>
      (window as unknown as { __emit: (e: string, p: unknown) => void }).__emit(
        name as string,
        data,
      ),
    [event, payload],
  );

const calls = (page: Page) =>
  page.evaluate(() => (window as unknown as { __calls: string[] }).__calls);

test.describe("Account and sync (mocked Tauri)", () => {
  test("signed out: hint, header, login form with error then success", async ({
    page,
  }) => {
    await installTauriMock(page, { signedIn: false, pending: 0 });
    await page.goto("/");
    await expect(
      page.getByText("Войдите, чтобы видеть встречи с сайта"),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Не выполнен вход" }),
    ).toBeVisible();

    await page
      .getByRole("navigation")
      .getByRole("button", { name: "Аккаунт", exact: true })
      .click();
    await page.getByLabel("Почта").fill("boss@example.com");
    await page.getByLabel("Пароль", { exact: true }).fill("wrong");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByRole("alert")).toHaveText(
      "Неверный логин или пароль",
    );

    await page.getByLabel("Пароль", { exact: true }).fill("right");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByText("boss@example.com")).toBeVisible();
    await expect(page.getByRole("button", { name: "Выйти" })).toBeVisible();
  });

  test("clear cross is shown for a non-empty field and keeps the focus", async ({
    page,
  }) => {
    await installTauriMock(page, { signedIn: false, pending: 0 });
    await page.goto("/");
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "Аккаунт", exact: true })
      .click();
    const email = page.getByLabel("Почта");
    await email.fill("a@b.ru");
    await page.getByRole("button", { name: "Очистить почту" }).click();
    await expect(email).toHaveValue("");
    await expect(email).toBeFocused();
    const fontSize = await email.evaluate((el) =>
      parseFloat(getComputedStyle(el).fontSize),
    );
    expect(fontSize).toBeGreaterThanOrEqual(16);
  });

  test("header shows the queue and a click starts the sync", async ({
    page,
  }) => {
    await installTauriMock(page, { signedIn: true, pending: 3 });
    await page.goto("/");
    const indicator = page.getByRole("button", { name: "В очереди: 3" });
    await expect(indicator).toBeVisible();
    await indicator.click();
    await expect.poll(() => calls(page)).toContain("sync_now");
  });

  test("badges: error with retry, empty, no-storage note, open on site", async ({
    page,
  }) => {
    await installTauriMock(page, { signedIn: true, pending: 0 });
    await page.goto("/");
    await expect(page.getByText("Пустая", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Ошибка отправки", { exact: true }),
    ).toBeVisible();

    await page.getByText("Отправленная встреча").click();
    await expect(page.getByText("аудио не отправлено")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Открыть на сайте" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "К списку встреч" }).click();

    await page.getByText("Отказ сервера").click();
    await page.getByRole("button", { name: "Повторить" }).click();
    await expect.poll(() => calls(page)).toContain("retry_meeting_sync");
    await emit(page, "sync-state", {
      meeting_id: "m-broken",
      status: {
        online: true,
        running: false,
        pending_count: 1,
        last_error: null,
        last_sync_at: null,
        syncing_meeting_id: null,
      },
    });
    await expect(page.getByText("Не отправлена")).toBeVisible();
    await expect(page.getByRole("button", { name: "Повторить" })).toHaveCount(
      0,
    );
  });
});
