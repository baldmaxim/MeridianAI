import { test, expect, type Page } from "@playwright/test";

/**
 * Meeting context (type, key terms, opponent's weak points): the new-meeting
 * dialog, the autosaving tab of a local meeting and the read-only tab of a
 * site meeting, with a mocked Tauri bridge. Set MERIDIAN_SHOTS_DIR to also
 * save screenshots.
 */

const SHOTS_DIR = process.env.MERIDIAN_SHOTS_DIR;

const shot = async (page: Page, name: string) => {
  if (SHOTS_DIR) {
    await page.waitForTimeout(350);
    await page.screenshot({
      path: `${SHOTS_DIR}/${name}`,
      type: "jpeg",
      quality: 88,
    });
  }
};

const LOCAL = {
  id: "m-local",
  title: "Совещание по смете",
  capture_mode: "in_person",
  started_at: "2026-10-20T15:30:00+03:00",
  ended_at: "2026-10-20T15:40:05+03:00",
  status: "stopped",
  duration_seconds: 605,
  server_meeting_id: null,
  sync_state: "pending",
  sync_error: null,
  synced_at: null,
  customer_id: null,
  object_id: null,
  customer_name: null,
  object_name: null,
  audio_state: "pending",
  web_url: null,
  negotiation_type: "Претензионная работа",
  key_terms: null,
  opponent_weaknesses: "Срывал сроки поставки",
};

const SERVER_BASE = {
  meeting_topic: null,
  ended_at: null,
  customer_id: null,
  customer_name: null,
  object_id: null,
  object_name: null,
  finalization_status: "completed",
  protocol_ready: true,
  micro_summary: null,
  client_uuid: null,
  source: "web",
};

const ITEMS = [
  {
    ...SERVER_BASE,
    meeting_id: 102,
    title: "Приёмка фасада",
    started_at: "2026-10-18T10:00:00+03:00",
  },
  {
    ...SERVER_BASE,
    meeting_id: 103,
    title: "Закупка арматуры",
    started_at: "2026-10-17T14:00:00+03:00",
  },
];

const VIEWS = {
  102: {
    ...ITEMS[0],
    protocol_markdown: "## Решения\n\n- Принять фасад",
    segments: [],
    documents: [],
    negotiation_type: "Согласование условий",
    key_terms: "Сдача до 15 ноября\nШтраф 0,1% в день",
    opponent_weaknesses: null,
    app_notes: "Уточнить марку бетона",
  },
  103: {
    ...ITEMS[1],
    protocol_markdown: "## Итоги",
    segments: [],
    documents: [],
  },
};

const installTauriMock = async (page: Page) => {
  await page.addInitScript(
    (fixtures) => {
      type Handler = (payload: unknown) => void;
      const callbacks = new Map<number, Handler>();
      const listeners = new Map<string, number[]>();
      let nextId = 1;
      const w = window as unknown as Record<string, unknown>;
      const calls: string[] = [];
      const allArgs: Record<string, unknown[]> = {};
      w.__calls = calls;
      w.__allArgs = allArgs;
      const list: Record<string, unknown>[] = [{ ...fixtures.local }];
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
      const answer = (cmd: string, args?: Record<string, unknown>): unknown => {
        calls.push(cmd);
        (allArgs[cmd] ??= []).push(args);
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
          case "get_meeting": {
            const meeting = list.find((m) => m.id === args?.id) ?? list[0];
            return { meeting, segments: [], notes: [] };
          }
          case "get_account":
            return account;
          case "get_sync_status":
            return {
              online: true,
              running: false,
              pending_count: 0,
              last_error: null,
              last_sync_at: null,
              syncing_meeting_id: null,
            };
          case "library_get":
            return {
              items: fixtures.items,
              projects: [],
              fetched_at: "2026-10-21T08:30:00+03:00",
              offline: false,
              signed_in: true,
            };
          case "search_meetings":
            return [];
          case "meeting_view_get":
            return {
              view: (fixtures.views as Record<string, unknown>)[
                String(args?.serverMeetingId)
              ],
              from_cache: false,
            };
          case "set_meeting_context": {
            const meeting = list.find((m) => m.id === args?.meetingId);
            if (meeting) {
              meeting.negotiation_type = args?.negotiationType;
              meeting.key_terms = args?.keyTerms;
              meeting.opponent_weaknesses = args?.opponentWeaknesses;
            }
            return meeting ?? null;
          }
          case "start_meeting": {
            const request = args?.request as Record<string, unknown>;
            const created = {
              ...fixtures.local,
              id: "m-new",
              title: request.title,
              status: "recording",
              negotiation_type: request.negotiation_type ?? null,
              key_terms: request.key_terms ?? null,
              opponent_weaknesses: request.opponent_weaknesses ?? null,
            };
            list.unshift(created);
            return created;
          }
          case "list_capture_devices":
            return { inputs: [], system_sources: [], system_supported: false };
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
    { local: LOCAL, items: ITEMS, views: VIEWS },
  );
};

const argsOf = (page: Page, cmd: string) =>
  page.evaluate(
    (name) =>
      (window as unknown as { __allArgs: Record<string, unknown[]> }).__allArgs[
        name
      ] ?? [],
    cmd,
  );

const open = async (page: Page) => {
  await page.clock.setFixedTime(new Date("2026-10-21T12:00:00+03:00"));
  await installTauriMock(page);
  await page.goto("/");
};

test.describe("Meeting context (mocked Tauri)", () => {
  test.use({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    timezoneId: "Europe/Moscow",
  });

  test("new meeting: the context is collapsed and goes to start_meeting", async ({
    page,
  }) => {
    await open(page);
    await page.getByRole("button", { name: "Новая встреча" }).click();
    const dialog = page.getByRole("dialog");
    const toggle = dialog.getByRole("button", {
      name: "Контекст встречи (необязательно)",
    });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(
      dialog.getByLabel("Тип переговоров", { exact: true }),
    ).toHaveCount(0);

    await toggle.click();
    await dialog
      .getByLabel("Тип переговоров", { exact: true })
      .fill("Продажа / заключение сделки");
    await dialog
      .getByLabel("Ключевые условия / цели", { exact: true })
      .fill("Целевая сумма 5 млн");
    await shot(page, "15-new-context.jpg");

    await dialog.getByRole("button", { name: "Начать запись" }).click();
    await expect.poll(() => argsOf(page, "start_meeting")).toHaveLength(1);
    const [args] = (await argsOf(page, "start_meeting")) as {
      request: Record<string, unknown>;
    }[];
    expect(args.request).toMatchObject({
      negotiation_type: "Продажа / заключение сделки",
      key_terms: "Целевая сумма 5 млн",
      opponent_weaknesses: null,
    });
  });

  test("local meeting: debounced autosave, the clear cross sends null", async ({
    page,
  }) => {
    await open(page);
    await page.getByRole("heading", { name: "Совещание по смете" }).click();
    await page.getByRole("tab", { name: "Контекст" }).click();

    const keyTerms = page.getByLabel("Ключевые условия / цели", {
      exact: true,
    });
    await expect(
      page.getByLabel("Тип переговоров", { exact: true }),
    ).toHaveValue("Претензионная работа");
    await expect(
      page.getByLabel("Слабые стороны оппонента", { exact: true }),
    ).toHaveValue("Срывал сроки поставки");
    // Nothing typed: nothing sent, and no cross on an empty field.
    await expect(
      page.getByRole("button", { name: "Очистить: Ключевые условия / цели" }),
    ).toBeHidden();
    expect(await argsOf(page, "set_meeting_context")).toHaveLength(0);

    await keyTerms.fill("Сдача до 15 ноября");
    expect(await argsOf(page, "set_meeting_context")).toHaveLength(0);
    await expect(page.getByText("Сохранено", { exact: true })).toBeVisible();
    expect(await argsOf(page, "set_meeting_context")).toEqual([
      {
        meetingId: "m-local",
        negotiationType: "Претензионная работа",
        keyTerms: "Сдача до 15 ноября",
        opponentWeaknesses: "Срывал сроки поставки",
      },
    ]);
    await shot(page, "14-context.jpg");

    await page
      .getByRole("button", { name: "Очистить: Ключевые условия / цели" })
      .click();
    await expect(keyTerms).toBeFocused();
    await expect(keyTerms).toHaveValue("");
    await expect
      .poll(async () => (await argsOf(page, "set_meeting_context")).length)
      .toBe(2);
    expect((await argsOf(page, "set_meeting_context"))[1]).toMatchObject({
      keyTerms: null,
    });
  });

  test("local meeting: unsaved edits are flushed on leaving the tab", async ({
    page,
  }) => {
    await open(page);
    await page.getByRole("heading", { name: "Совещание по смете" }).click();
    await page.getByRole("tab", { name: "Контекст" }).click();
    await page
      .getByLabel("Слабые стороны оппонента", { exact: true })
      .fill("Нет лицензии");
    await page.getByRole("tab", { name: "Транскрипт" }).click();
    await expect
      .poll(async () => (await argsOf(page, "set_meeting_context")).length)
      .toBe(1);
    expect((await argsOf(page, "set_meeting_context"))[0]).toMatchObject({
      opponentWeaknesses: "Нет лицензии",
    });
  });

  test("site meeting: context is read-only, empty fields say so", async ({
    page,
  }) => {
    await open(page);
    await page.getByText("Приёмка фасада").click();
    await page.getByRole("tab", { name: "Контекст" }).click();
    await expect(page.getByText("Согласование условий")).toBeVisible();
    await expect(page.getByText("Штраф 0,1% в день")).toBeVisible();
    await expect(page.getByText("Заметки из приложения")).toBeVisible();
    await expect(page.getByText("Уточнить марку бетона")).toBeVisible();
    await expect(page.getByText("не задано")).toHaveCount(1);
    await expect(page.getByRole("textbox")).toHaveCount(0);

    await page.getByRole("button", { name: "К списку встреч" }).click();
    await page.getByText("Закупка арматуры").click();
    await page.getByRole("tab", { name: "Контекст" }).click();
    await expect(page.getByText("не задано")).toHaveCount(3);
    await expect(page.getByText("Заметки из приложения")).toHaveCount(0);
  });
});
