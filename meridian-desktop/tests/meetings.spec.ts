import { test, expect, type Page } from "@playwright/test";

/**
 * Smoke tests of the meetings UI with a mocked Tauri bridge: `invoke` is
 * answered from a fixture, events are delivered through `window.__emit`.
 */

const MEETINGS = [
  {
    id: "m-stopped",
    title: "Совещание по смете",
    capture_mode: "in_person",
    started_at: "2026-10-20T09:00:00.000Z",
    ended_at: "2026-10-20T09:10:05.000Z",
    status: "stopped",
    duration_seconds: 605,
    server_meeting_id: null,
    sync_state: "pending",
    sync_error: null,
    synced_at: null,
    customer_id: null,
    object_id: null,
  },
  {
    id: "m-broken",
    title: "Обрезанная запись",
    capture_mode: "online",
    started_at: "2026-10-21T09:00:00.000Z",
    ended_at: null,
    status: "interrupted",
    duration_seconds: 75,
    server_meeting_id: null,
    sync_state: "pending",
    sync_error: null,
    synced_at: null,
    customer_id: null,
    object_id: null,
  },
];

const installTauriMock = async (page: Page) => {
  await page.addInitScript((meetings) => {
    type Handler = (payload: unknown) => void;
    const callbacks = new Map<number, Handler>();
    const listeners = new Map<string, number[]>();
    let nextId = 1;
    const settings = {
      onboarding_completed: true,
      selected_model: "gigaam",
      theme: "dark",
      accent_color: "amber",
      debug_mode: false,
      post_process_enabled: false,
    };
    const details = {
      meeting: meetings[0],
      segments: [
        {
          id: "s1",
          meeting_id: "m-stopped",
          channel: "mixed",
          start_time: 3,
          end_time: 6,
          text: "Первая фраза",
          created_at: "",
          synced: false,
          voice: null,
        },
        {
          id: "s-voice",
          meeting_id: "m-stopped",
          channel: "system",
          start_time: 7,
          end_time: 8,
          text: "Фраза голоса",
          created_at: "",
          synced: false,
          voice: "Голос 1",
        },
      ],
      notes: [
        {
          id: "n1",
          meeting_id: "m-stopped",
          at_seconds: 4,
          text: "Проверить объёмы",
          updated_at: "",
        },
      ],
    };
    const answer = (cmd: string): unknown => {
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
          return meetings;
        case "get_active_meeting":
          return null;
        case "get_meeting":
          return details;
        case "meeting_voices_list":
          return [
            {
              label: "Голос 1",
              side: "opponent",
              count: 5,
              first_channel: "system",
            },
          ];
        case "list_capture_devices":
          return { inputs: [], system_sources: [], system_supported: false };
        case "plugin:event|listen": {
          return 1;
        }
        default:
          return null;
      }
    };
    const w = window as unknown as Record<string, unknown>;
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
          const list = listeners.get(name) ?? [];
          list.push(Number(args.handler));
          listeners.set(name, list);
          return Number(args.handler);
        }
        if (cmd === "meeting_voice_set_side") {
          const calls = ((w.__calls as unknown[]) ??= []);
          calls.push({ cmd, args });
          return null;
        }
        return answer(cmd);
      },
    };
    w.__emit = (event: string, payload: unknown) => {
      for (const id of listeners.get(event) ?? []) {
        callbacks.get(id)?.({ event, id, payload });
      }
    };
  }, MEETINGS);
};

test.describe("Meetings UI (mocked Tauri)", () => {
  test.beforeEach(async ({ page }) => {
    await installTauriMock(page);
  });

  test("list shows cards, interrupted meeting offers resume", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByText("Совещание по смете")).toBeVisible();
    await expect(page.getByText("10:05")).toBeVisible();
    await expect(page.getByText("Не отправлена")).toBeVisible();
    await expect(page.getByText("Прервана")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Продолжить запись", exact: true }),
    ).toBeVisible();
  });

  test("meeting screen shows phrase and note, new phrase arrives by event", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByText("Совещание по смете").click();
    await expect(page.getByText("Первая фраза")).toBeVisible();
    await expect(page.getByText("Проверить объёмы").first()).toBeVisible();
    await page.evaluate(() =>
      (window as unknown as { __emit: (e: string, p: unknown) => void }).__emit(
        "meeting-segment",
        {
          segment: {
            id: "s2",
            meeting_id: "m-stopped",
            channel: "mic",
            start_time: 9,
            end_time: 12,
            text: "Вторая фраза",
            created_at: "",
            synced: false,
            voice: null,
          },
        },
      ),
    );
    await expect(page.getByText("Вторая фраза")).toBeVisible();
  });

  test("voice chip shows the side and changes it through the menu", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByText("Совещание по смете").click();
    const chip = page.getByRole("button", { name: "Голос 1 · Оппонент" });
    await expect(chip).toBeVisible();
    await chip.click();
    await page.getByRole("menuitemradio", { name: "Мы" }).click();
    await expect(
      page.getByRole("button", { name: "Голос 1 · Мы" }),
    ).toBeVisible();
    const calls = await page.evaluate(
      () => (window as unknown as { __calls: unknown[] }).__calls,
    );
    expect(calls).toEqual([
      {
        cmd: "meeting_voice_set_side",
        args: { meetingId: "m-stopped", label: "Голос 1", side: "self" },
      },
    ]);
  });
});
