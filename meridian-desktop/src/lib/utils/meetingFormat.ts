import type { MeetingInfo, MeetingStatus } from "@/bindings";

const pad = (value: number): string => String(value).padStart(2, "0");

/** mm:ss, or h:mm:ss from one hour on. Negative / invalid input gives 00:00. */
export const formatClock = (seconds: number): string => {
  const total =
    Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(secs)}`
    : `${pad(minutes)}:${pad(secs)}`;
};

/** "Встреча dd.mm.yyyy hh:mm"-style date part for the default title. */
export const formatTitleDate = (date: Date): string =>
  `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;

/** Localized start date and time of a meeting (ISO string from the backend). */
export const formatStartedAt = (iso: string, locale: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

export type SyncKind = "pending" | "synced" | "error" | "empty";

/** Maps the backend's free-form sync_state to a known badge, or null. */
export const toSyncKind = (syncState: string): SyncKind | null => {
  switch (syncState) {
    case "pending":
      return "pending";
    case "synced":
      return "synced";
    case "error":
      return "error";
    case "empty":
      return "empty";
    default:
      return null;
  }
};

export const isResumable = (meeting: MeetingInfo): boolean =>
  (meeting.status === "interrupted" || meeting.status === "stopped") &&
  meeting.sync_state !== "synced";

/** Newest first, by start time. */
export const sortMeetings = (meetings: MeetingInfo[]): MeetingInfo[] =>
  [...meetings].sort((a, b) => b.started_at.localeCompare(a.started_at));

/** Model-related backend errors get a link to the model settings. */
export const isModelError = (message: string): boolean =>
  /модел|model/i.test(message);
