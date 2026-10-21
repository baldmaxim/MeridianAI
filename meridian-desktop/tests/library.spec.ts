import { test, expect, type Page } from "@playwright/test";

/**
 * Smoke tests of the library of meetings (local + site), the project filter,
 * search, the read-only site meeting, "Ask" and the project choice, with a
 * mocked Tauri bridge. Set MERIDIAN_SHOTS_DIR to also save screenshots.
 */

const SHOTS_DIR = process.env.MERIDIAN_SHOTS_DIR;

const shot = async (page: Page, name: string) => {
  if (SHOTS_DIR) {
    // Let the 200 ms enter animations finish.
    await page.waitForTimeout(350);
    await page.screenshot({
      path: `${SHOTS_DIR}/${name}`,
      type: "jpeg",
      quality: 88,
    });
  }
};

interface MockOptions {
  signedIn: boolean;
  offline: boolean;
  /** Adds a site meeting with an object but no customer (old data). */
  legacy?: boolean;
}

const BASE_LOCAL = {
  capture_mode: "in_person",
  ended_at: null,
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
};

const LOCALS = [
  {
    ...BASE_LOCAL,
    id: "m-synced",
    title: "Планёрка по объекту",
    started_at: "2026-10-21T09:00:00+03:00",
    ended_at: "2026-10-21T09:25:10+03:00",
    duration_seconds: 1510,
    sync_state: "synced",
    server_meeting_id: 101,
    customer_id: 1,
    object_id: 11,
    customer_name: "СтройИнвест",
    object_name: "Корпус А",
    web_url: "https://meridianai.ru/meetings/101",
  },
  {
    ...BASE_LOCAL,
    id: "m-pending",
    title: "Совещание по смете",
    started_at: "2026-10-20T15:30:00+03:00",
    ended_at: "2026-10-20T15:40:05+03:00",
  },
  {
    ...BASE_LOCAL,
    id: "m-broken",
    title: "Обрезанная запись",
    started_at: "2026-10-19T11:00:00+03:00",
    status: "interrupted",
    duration_seconds: 75,
  },
];

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
    meeting_id: 101,
    title: "Планёрка по объекту (сайт)",
    started_at: "2026-10-21T09:00:00+03:00",
    customer_id: 1,
    customer_name: "СтройИнвест",
    object_id: 11,
    object_name: "Корпус А",
    micro_summary: "Согласованы сроки бетонирования",
    client_uuid: "m-synced",
    source: "desktop",
  },
  {
    ...SERVER_BASE,
    meeting_id: 102,
    title: "Приёмка фасада",
    started_at: "2026-10-18T10:00:00+03:00",
    ended_at: "2026-10-18T10:48:00+03:00",
    customer_id: 1,
    customer_name: "СтройИнвест",
    object_id: 12,
    object_name: "Корпус Б",
    micro_summary: "Фасад принят с замечаниями по швам и откосам",
  },
  {
    ...SERVER_BASE,
    meeting_id: 103,
    title: "Закупка арматуры",
    started_at: "2026-10-17T14:00:00+03:00",
    customer_id: 2,
    customer_name: "ГорСтрой",
    finalization_status: "running",
    protocol_ready: false,
  },
  {
    ...SERVER_BASE,
    meeting_id: 104,
    title: "Встреча с поставщиком",
    started_at: "2026-10-10T12:00:00+03:00",
    finalization_status: "not_started",
    protocol_ready: false,
    client_uuid: "gone-uuid",
    source: "desktop",
  },
];

// Empty customers go first on purpose: the panel must still sort them last.
const PROJECTS = [
  {
    id: 3,
    name: "Яркий Дом",
    objects: [{ id: 31, name: "Литер 1", address: null }],
  },
  {
    id: 4,
    name: "Альфа-Монтаж",
    objects: [],
  },
  {
    id: 1,
    name: "СтройИнвест",
    objects: [
      { id: 11, name: "Корпус А", address: null },
      { id: 12, name: "Корпус Б", address: null },
    ],
  },
  {
    id: 2,
    name: "ГорСтрой",
    objects: [{ id: 21, name: "Склад", address: null }],
  },
];

const LEGACY_ITEM = {
  ...SERVER_BASE,
  meeting_id: 105,
  title: "Старая встреча по складу",
  started_at: "2026-10-16T09:00:00+03:00",
  object_id: 21,
  object_name: "Склад",
};

const VIEW_102 = {
  ...ITEMS[1],
  protocol_markdown:
    "## Решения\n\n- Принять фасад с замечаниями\n- Устранить **швы** до 15 ноября\n\n## Риски\n\n1. Погода\n2. Поставка откосов",
  segments: [
    {
      text: "Начинаем приёмку фасада.",
      speaker_label: "Иван Петров",
      start_time: 3,
      end_time: 6,
      wall_clock: null,
    },
    {
      text: "По швам есть замечания, зафиксируйте их в акте.",
      speaker_label: "Заказчик",
      start_time: 70,
      end_time: 76,
      wall_clock: null,
    },
  ],
  documents: [
    {
      filename: "Договор подряда.pdf",
      doc_type: "contract",
      doc_type_label: "Договор",
      page_count: 12,
    },
    {
      filename: "Смета.xlsx",
      doc_type: "estimate",
      doc_type_label: "Смета",
      page_count: null,
    },
  ],
};

const VIEW_101 = {
  ...ITEMS[0],
  protocol_markdown:
    "## Итоги планёрки\n\n- Бетонирование начать в понедельник",
  segments: [],
  documents: [],
};

const DETAILS = {
  "m-synced": {
    segments: [
      {
        id: "s1",
        meeting_id: "m-synced",
        channel: "mic",
        start_time: 3,
        end_time: 8,
        text: "Начинаем планёрку, у нас три вопроса по графику.",
        created_at: "",
        synced: true,
        voice: null,
      },
      {
        id: "s2",
        meeting_id: "m-synced",
        channel: "system",
        start_time: 12,
        end_time: 20,
        text: "По бетону поставщик подтвердил поставку на понедельник.",
        created_at: "",
        synced: true,
        voice: null,
      },
    ],
    notes: [
      {
        id: "n1",
        meeting_id: "m-synced",
        at_seconds: 14,
        text: "Уточнить марку бетона у поставщика",
        updated_at: "",
      },
      {
        id: "n2",
        meeting_id: "m-synced",
        at_seconds: 40,
        text: "Прислать график заказчику до пятницы",
        updated_at: "",
      },
    ],
  },
};

const installTauriMock = async (page: Page, options: MockOptions) => {
  await page.addInitScript(
    (fixtures) => {
      type Handler = (payload: unknown) => void;
      const callbacks = new Map<number, Handler>();
      const listeners = new Map<string, number[]>();
      let nextId = 1;
      const w = window as unknown as Record<string, unknown>;
      const calls: string[] = [];
      const lastArgs: Record<string, unknown> = {};
      w.__calls = calls;
      w.__args = lastArgs;
      const list = fixtures.locals.map((m) => ({ ...m }));
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
      const snapshot = () =>
        fixtures.opts.signedIn
          ? {
              items: fixtures.items,
              projects: fixtures.projects,
              fetched_at: "2026-10-21T08:30:00+03:00",
              offline: fixtures.opts.offline,
              signed_in: true,
            }
          : {
              items: [],
              projects: [],
              fetched_at: null,
              offline: false,
              signed_in: false,
            };
      const answer = (cmd: string, args?: Record<string, unknown>): unknown => {
        calls.push(cmd);
        if (args) lastArgs[cmd] = args;
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
            const extra = (fixtures.details as Record<string, object>)[
              meeting.id
            ] ?? { segments: [], notes: [] };
            return { meeting, ...extra };
          }
          case "get_account":
            return fixtures.opts.signedIn ? account : null;
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
            return snapshot();
          case "search_meetings":
            return fixtures.hits;
          case "meeting_view_get": {
            const view =
              args?.serverMeetingId === 101
                ? fixtures.view101
                : fixtures.view102;
            return { view, from_cache: fixtures.opts.offline };
          }
          case "meeting_ask": {
            if (String(args?.question).includes("сбой")) throw "Нет сети";
            return {
              answer:
                "Фасад принят **с замечаниями**:\n\n- швы — устранить до 15 ноября\n- откосы — переделать",
              sources: [
                { kind: "transcript", title: "Приёмка фасада", ref: "102" },
                { kind: "document", title: "Договор подряда.pdf", ref: null },
              ],
            };
          }
          case "set_meeting_project": {
            const meeting = list.find((m) => m.id === args?.meetingId);
            if (meeting) {
              meeting.customer_id = args?.customerId as number | null;
              meeting.object_id = args?.objectId as number | null;
              meeting.customer_name = args?.customerName as string | null;
              meeting.object_name = args?.objectName as string | null;
            }
            return meeting ?? null;
          }
          case "start_meeting": {
            const request = args?.request as Record<string, unknown>;
            const created = {
              ...fixtures.locals[1],
              id: "m-new",
              title: request.title,
              status: "recording",
              customer_id: request.customer_id,
              object_id: request.object_id,
              customer_name: request.customer_name,
              object_name: request.object_name,
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
    {
      locals: LOCALS,
      items: options.legacy ? [...ITEMS, LEGACY_ITEM] : ITEMS,
      projects: PROJECTS,
      view101: VIEW_101,
      view102: VIEW_102,
      details: DETAILS,
      hits: [
        {
          kind: "local",
          id: "m-synced",
          title: "Планёрка по объекту",
          snippet: "…поставщик подтвердил поставку [бетон]а на понедельник…",
          started_at: "2026-10-21T09:00:00+03:00",
        },
        {
          kind: "server",
          id: "102",
          title: "Приёмка фасада",
          snippet: "Замечания по швам: [бетон]ные откосы переделать",
          started_at: "2026-10-18T10:00:00+03:00",
        },
      ],
      opts: options,
    },
  );
};

const calls = (page: Page) =>
  page.evaluate(() => (window as unknown as { __calls: string[] }).__calls);

const lastArgs = (page: Page, cmd: string) =>
  page.evaluate(
    (name) =>
      (window as unknown as { __args: Record<string, unknown> }).__args[name],
    cmd,
  );

const projectsNav = (page: Page) =>
  page.getByRole("navigation", { name: "Проекты" });

const open = async (page: Page, options: Partial<MockOptions> = {}) => {
  await page.clock.setFixedTime(new Date("2026-10-21T12:00:00+03:00"));
  await installTauriMock(page, { signedIn: true, offline: false, ...options });
  await page.goto("/");
};

test.describe("Library (mocked Tauri)", () => {
  test.use({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    timezoneId: "Europe/Moscow",
  });

  test("mixed local and site meetings, dedup, grouping by day", async ({
    page,
  }) => {
    await open(page);
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(6);
    // The site copy of the local meeting is one card, with the local title.
    await expect(page.getByText("Планёрка по объекту (сайт)")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Планёрка по объекту" }),
    ).toHaveCount(1);
    await expect(page.getByText("Сегодня", { exact: true })).toBeVisible();
    await expect(page.getByText("Вчера", { exact: true })).toBeVisible();
    await expect(page.getByText("19 октября", { exact: true })).toBeVisible();
    await expect(page.getByText("Протокол готов")).toHaveCount(2);
    await expect(page.getByText("На сервере", { exact: true })).toHaveCount(2);
    await expect(page.getByText("Не отправлена")).toHaveCount(1);
    await expect(page.getByText("Прервана")).toBeVisible();
    await expect(
      page.getByText("Согласованы сроки бетонирования"),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: "С сайта" }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: "Записана в приложении" }).first(),
    ).toBeVisible();
    await shot(page, "6-library.jpg");
  });

  test("project filter: customer, object, no project", async ({ page }) => {
    await open(page);
    const nav = projectsNav(page);
    await expect(
      nav.getByRole("button", { name: /^Все встречи\s*6$/ }),
    ).toBeVisible();
    await nav.getByRole("button", { name: /^СтройИнвест/ }).click();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(2);
    await nav.getByRole("button", { name: /^Корпус Б/ }).click();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(1);
    await expect(page.getByText("Приёмка фасада")).toBeVisible();
    await nav.getByRole("button", { name: /^Без проекта/ }).click();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(3);
    await nav.getByRole("button", { name: /^Все встречи/ }).click();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(6);
  });

  test("projects with meetings go first; empty ones are muted, no badge", async ({
    page,
  }) => {
    await open(page);
    const nav = projectsNav(page);
    const names = await nav.getByRole("button").allInnerTexts();
    const order = names
      .map((n) => n.split("\n")[0].trim())
      .filter((n) => /^(СтройИнвест|ГорСтрой|Альфа-Монтаж|Яркий Дом)$/.test(n));
    expect(order).toEqual([
      "СтройИнвест",
      "ГорСтрой",
      "Альфа-Монтаж",
      "Яркий Дом",
    ]);
    await expect(
      nav.getByRole("button", { name: /^СтройИнвест\s*2$/ }),
    ).toBeVisible();
    await expect(
      nav.getByRole("button", { name: /^ГорСтрой\s*1$/ }),
    ).toBeVisible();
    // An empty folder has no count at all.
    await expect(
      nav.getByRole("button", { name: /^Альфа-Монтаж$/ }),
    ).toBeVisible();
    await expect(
      nav.getByRole("button", { name: /^Яркий Дом$/ }),
    ).toBeVisible();
    await expect(nav.getByRole("separator")).toHaveText("Без встреч");
    await shot(page, "13-projects.jpg");
  });

  test("a meeting with an object only belongs to the customer of the object", async ({
    page,
  }) => {
    await open(page, { legacy: true });
    const nav = projectsNav(page);
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(7);
    await expect(
      nav.getByRole("button", { name: /^ГорСтрой\s*2$/ }),
    ).toBeVisible();
    await expect(
      nav.getByRole("button", { name: /^Без проекта\s*3$/ }),
    ).toBeVisible();
    await nav.getByRole("button", { name: /^ГорСтрой/ }).click();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(2);
    await expect(page.getByText("Старая встреча по складу")).toBeVisible();
    await nav.getByRole("button", { name: /^Склад\s*1$/ }).click();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(1);
    await expect(page.getByText("Старая встреча по складу")).toBeVisible();
    await nav.getByRole("button", { name: /^Без проекта/ }).click();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(3);
    await expect(page.getByText("Старая встреча по складу")).toHaveCount(0);
  });

  test("search shows snippets with highlights and opens the hits", async ({
    page,
  }) => {
    await open(page);
    const search = page.getByRole("searchbox", { name: "Поиск по встречам" });
    await search.fill("бетон");
    await expect(page.locator("mark")).toHaveCount(2);
    await expect(page.locator("mark").first()).toHaveText("бетон");
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(0);
    expect(await lastArgs(page, "search_meetings")).toMatchObject({
      query: "бетон",
    });
    await shot(page, "7-search.jpg");

    // A site hit with no local copy opens the read-only meeting.
    await page.getByRole("button", { name: /Приёмка фасада/ }).click();
    await expect(page.getByRole("heading", { name: "Решения" })).toBeVisible();

    await page.getByRole("button", { name: "К списку встреч" }).click();
    await page.getByRole("searchbox", { name: "Поиск по встречам" }).fill("бе");
    await page
      .getByRole("button", { name: /Планёрка по объекту/ })
      .first()
      .click();
    await expect(page.getByLabel("Название встречи")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Остановить" })).toHaveCount(
      0,
    );
    await expect(page.getByText("Уточнить марку бетона").first()).toBeVisible();
  });

  test("a short query does not search; the clear cross resets", async ({
    page,
  }) => {
    await open(page);
    const search = page.getByRole("searchbox", { name: "Поиск по встречам" });
    await search.fill("б");
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(6);
    await search.fill("бетон");
    await expect(page.locator("mark").first()).toBeVisible();
    await page.getByRole("button", { name: "Очистить поиск" }).click();
    await expect(search).toHaveValue("");
    await expect(search).toBeFocused();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(6);
  });

  test("site meeting: protocol, transcript, documents, read-only", async ({
    page,
  }) => {
    await open(page);
    await page.getByText("Приёмка фасада").click();
    await expect(page.getByRole("heading", { name: "Решения" })).toBeVisible();
    await expect(page.getByText("Принять фасад с замечаниями")).toBeVisible();
    await expect(page.getByText("Иван Петров")).toBeVisible();
    await expect(page.getByText("00:03")).toBeVisible();
    await expect(page.getByText("Из кэша")).toHaveCount(0);
    await expect(page.getByLabel("Название встречи")).toHaveCount(0);
    await shot(page, "9-server-meeting.jpg");

    await page.getByRole("tab", { name: "Документы" }).click();
    await expect(page.getByText("Договор подряда.pdf")).toBeVisible();
    await expect(page.getByText("Стр.: 12")).toBeVisible();

    // The panel collapses and the choice is remembered.
    await page.getByRole("button", { name: "Свернуть панель" }).click();
    await expect(page.getByRole("tab", { name: "Документы" })).toHaveCount(0);
    expect(
      await page.evaluate(() =>
        window.localStorage.getItem("meridian.meetingSidePanelCollapsed"),
      ),
    ).toBe("1");
    await page.getByRole("button", { name: "Развернуть панель" }).click();
    await expect(page.getByRole("tab", { name: "Документы" })).toBeVisible();
  });

  test("site meeting from the cache shows the badge", async ({ page }) => {
    await open(page, { offline: true });
    await expect(
      page.getByText("Нет сети — показаны сохранённые данные, обновлено"),
    ).toBeVisible();
    await page.getByText("Приёмка фасада").click();
    await expect(page.getByText("Из кэша")).toBeVisible();
  });

  test("ask: answer in markdown with sources, errors in the chat", async ({
    page,
  }) => {
    await open(page);
    await page.getByText("Приёмка фасада").click();
    await page.getByRole("tab", { name: "Спросить" }).click();
    const input = page.getByRole("textbox", { name: "Спросите о встрече…" });
    await input.fill("Что решили по фасаду?");
    await input.press("Shift+Enter");
    await expect(input).toHaveValue("Что решили по фасаду?\n");
    await input.press("Enter");
    await expect(page.getByText("Что решили по фасаду?")).toBeVisible();
    await expect(page.getByText("швы — устранить до 15 ноября")).toBeVisible();
    await expect(
      page.getByRole("list", { name: "Источники" }).getByRole("listitem"),
    ).toHaveCount(2);
    expect(await lastArgs(page, "meeting_ask")).toMatchObject({
      serverMeetingId: 102,
    });
    await shot(page, "10-ask.jpg");

    await input.fill("сбой связи");
    await input.press("Enter");
    await expect(page.getByRole("alert")).toContainText("Нет сети");

    // The history stays when the tab is switched.
    await page.getByRole("tab", { name: "Транскрипт" }).click();
    await page.getByRole("tab", { name: "Спросить" }).click();
    await expect(page.getByText("швы — устранить до 15 ноября")).toBeVisible();
  });

  test("new meeting: project select, pre-filled from the filter", async ({
    page,
  }) => {
    await open(page);
    await projectsNav(page)
      .getByRole("button", { name: /^СтройИнвест/ })
      .click();
    await page.getByRole("button", { name: "Новая встреча" }).click();
    const dialog = page.getByRole("dialog");
    const customer = dialog.getByLabel("Заказчик");
    await expect(customer).toHaveValue("1");
    await expect(dialog.getByLabel("Объект")).toHaveValue("");
    await expect(dialog.getByLabel("Объект").locator("option")).toHaveCount(3);
    await dialog.getByLabel("Объект").selectOption("12");
    await shot(page, "11-new-meeting.jpg");

    await customer.selectOption("2");
    await expect(dialog.getByLabel("Объект")).toHaveValue("");
    await expect(dialog.getByLabel("Объект").locator("option")).toHaveCount(2);
    await customer.selectOption("1");
    await dialog.getByLabel("Объект").selectOption("12");

    await page.getByRole("button", { name: "Начать запись" }).click();
    await expect.poll(() => calls(page)).toContain("start_meeting");
    const args = (await lastArgs(page, "start_meeting")) as {
      request: Record<string, unknown>;
    };
    expect(args.request).toMatchObject({
      customer_id: 1,
      object_id: 12,
      customer_name: "СтройИнвест",
      object_name: "Корпус Б",
    });
  });

  test("local meeting: notes, transcript, protocol, ask, project chip", async ({
    page,
  }) => {
    await open(page);
    await page.getByRole("heading", { name: "Планёрка по объекту" }).click();
    await expect(
      page.getByText("Уточнить марку бетона у поставщика").first(),
    ).toBeVisible();
    await expect(
      page.getByText("Начинаем планёрку, у нас три вопроса по графику."),
    ).toBeVisible();
    await expect(page.getByText("21 октября 2026")).toBeVisible();
    // On the site the project is changed there: the chip is not a button.
    await expect(page.getByRole("button", { name: /СтройИнвест/ })).toHaveCount(
      0,
    );
    await expect(
      page.locator('[title="Проект меняется на сайте"]'),
    ).toContainText("СтройИнвест · Корпус А");
    await shot(page, "8-local-meeting.jpg");

    await page.getByRole("tab", { name: "Протокол" }).click();
    await expect(
      page.getByRole("heading", { name: "Итоги планёрки" }),
    ).toBeVisible();
    expect(await lastArgs(page, "meeting_view_get")).toMatchObject({
      serverMeetingId: 101,
    });

    await page.getByRole("button", { name: "К списку встреч" }).click();
    await page.getByRole("heading", { name: "Совещание по смете" }).click();
    await page.getByRole("tab", { name: "Протокол" }).click();
    await expect(
      page.getByText("Протокол появится после отправки встречи в Meridian"),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Спросить" }).click();
    await expect(
      page.getByText("Доступно после отправки встречи"),
    ).toBeVisible();

    // An unsent meeting: the project can be changed.
    await page.getByRole("button", { name: /Без проекта/ }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Заказчик").selectOption("2");
    await dialog.getByLabel("Объект").selectOption("21");
    await page.getByRole("button", { name: "Сохранить" }).click();
    await expect.poll(() => calls(page)).toContain("set_meeting_project");
    expect(await lastArgs(page, "set_meeting_project")).toMatchObject({
      meetingId: "m-pending",
      customerId: 2,
      objectId: 21,
      customerName: "ГорСтрой",
      objectName: "Склад",
    });
    await expect(page.getByText("ГорСтрой · Склад")).toBeVisible();
  });

  test("signed out: banner with a link to the account", async ({ page }) => {
    await open(page, { signedIn: false });
    await expect(
      page.getByText("Войдите, чтобы видеть встречи с сайта"),
    ).toBeVisible();
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(3);
    await page.getByRole("button", { name: "Войти", exact: true }).click();
    await expect(page.getByRole("tab", { name: "Аккаунт" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("a finished upload reloads the library from the server", async ({
    page,
  }) => {
    await open(page);
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(6);
    const count = async () =>
      (await calls(page)).filter((c) => c === "library_get").length;
    const before = await count();
    await page.evaluate(() =>
      (window as unknown as { __emit: (e: string, p: unknown) => void }).__emit(
        "sync-state",
        {
          meeting_id: "m-pending",
          status: {
            online: true,
            running: false,
            pending_count: 0,
            last_error: null,
            last_sync_at: null,
            syncing_meeting_id: null,
          },
        },
      ),
    );
    await expect.poll(count).toBeGreaterThan(before);
  });
});

test.describe("Library at the minimum window size (mocked Tauri)", () => {
  test.use({
    viewport: { width: 800, height: 600 },
    deviceScaleFactor: 1,
    timezoneId: "Europe/Moscow",
  });

  test("no horizontal scroll; projects collapse into a drop-down", async ({
    page,
  }) => {
    await open(page);
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(6);
    await expect(projectsNav(page)).toBeHidden();
    const select = page.getByRole("combobox", { name: /Проекты/ });
    await expect(select).toBeVisible();
    const labels = await select.locator("option").allInnerTexts();
    expect(labels.slice(2, 5)).toEqual([
      "СтройИнвест (2)",
      "Корпус А (1)",
      "Корпус Б (1)",
    ]);
    expect(labels).toContain("Альфа-Монтаж");
    expect(labels.indexOf("Альфа-Монтаж")).toBeGreaterThan(
      labels.indexOf("ГорСтрой (1)"),
    );
    await select.selectOption("c:1");
    await expect(page.getByRole("heading", { level: 3 })).toHaveCount(2);
    await select.selectOption("all");
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await shot(page, "12-library-800.jpg");

    await page.getByText("Приёмка фасада").click();
    await expect(page.getByRole("heading", { name: "Решения" })).toBeVisible();
    const overflowMeeting = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflowMeeting).toBeLessThanOrEqual(0);
  });
});
