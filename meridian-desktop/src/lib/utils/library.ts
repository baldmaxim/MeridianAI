import type {
  LibraryItem,
  LibrarySource,
  MeetingInfo,
  ProjectCustomer,
} from "@/bindings";

export type ProjectFilter =
  | { kind: "all" }
  | { kind: "none" }
  | { kind: "customer"; customerId: number }
  | { kind: "object"; customerId: number; objectId: number };

/** One card of the library: a local meeting, a site meeting, or both merged. */
export interface LibraryEntry {
  key: string;
  local: MeetingInfo | null;
  server: LibraryItem | null;
  /** Empty when the meeting has no title at all. */
  title: string;
  startedAt: string | null;
  durationSeconds: number | null;
  customerId: number | null;
  objectId: number | null;
  customerName: string | null;
  objectName: string | null;
  source: LibrarySource;
  summary: string | null;
}

interface ProjectFields {
  customerId: number | null;
  objectId: number | null;
  customerName: string | null;
  objectName: string | null;
}

const NO_PROJECT: ProjectFields = {
  customerId: null,
  objectId: null,
  customerName: null,
  objectName: null,
};

const projectOfLocal = (local: MeetingInfo): ProjectFields => ({
  customerId: local.customer_id,
  objectId: local.object_id,
  customerName: local.customer_name,
  objectName: local.object_name,
});

const projectOfServer = (server: LibraryItem): ProjectFields => ({
  customerId: server.customer_id,
  objectId: server.object_id,
  customerName: server.customer_name,
  objectName: server.object_name,
});

/** Old data of the site may have an object without its customer. */
const hasProject = (customerId: number | null, objectId: number | null) =>
  customerId !== null || objectId !== null;

/** The site is the source of truth once the meeting is there. */
const pickProject = (
  local: MeetingInfo | null,
  server: LibraryItem | null,
): ProjectFields => {
  if (server && hasProject(server.customer_id, server.object_id)) {
    return projectOfServer(server);
  }
  if (local && hasProject(local.customer_id, local.object_id)) {
    return projectOfLocal(local);
  }
  return NO_PROJECT;
};

const serverDuration = (server: LibraryItem): number | null => {
  if (!server.started_at || !server.ended_at) return null;
  const seconds =
    (new Date(server.ended_at).getTime() -
      new Date(server.started_at).getTime()) /
    1000;
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
};

const serverTitle = (server: LibraryItem): string =>
  server.title?.trim() || server.meeting_topic?.trim() || "";

const toEntry = (
  local: MeetingInfo | null,
  server: LibraryItem | null,
): LibraryEntry => ({
  key: local ? `l:${local.id}` : `s:${server?.meeting_id ?? ""}`,
  local,
  server,
  title: local?.title.trim() || (server ? serverTitle(server) : ""),
  startedAt: local?.started_at ?? server?.started_at ?? null,
  durationSeconds: local
    ? local.duration_seconds
    : server
      ? serverDuration(server)
      : null,
  ...pickProject(local, server),
  source: local ? "desktop" : (server?.source ?? "web"),
  summary: server?.micro_summary?.trim() || null,
});

const byStartDesc = (a: LibraryEntry, b: LibraryEntry): number => {
  if (a.startedAt === b.startedAt) return 0;
  if (a.startedAt === null) return 1;
  if (b.startedAt === null) return -1;
  return b.startedAt.localeCompare(a.startedAt);
};

/**
 * Merges the meetings recorded here with the ones of the site. A site item is
 * the same meeting as a local one when its `client_uuid` is the local id, or
 * the local meeting already knows its server id.
 */
export const mergeLibrary = (
  locals: MeetingInfo[],
  items: LibraryItem[],
): LibraryEntry[] => {
  const byServerId = new Map<number, LibraryItem>();
  const byClientUuid = new Map<string, LibraryItem>();
  for (const item of items) {
    byServerId.set(item.meeting_id, item);
    if (item.client_uuid) byClientUuid.set(item.client_uuid, item);
  }

  const used = new Set<number>();
  const entries = locals.map((local) => {
    const server =
      (local.server_meeting_id !== null
        ? byServerId.get(local.server_meeting_id)
        : undefined) ??
      byClientUuid.get(local.id) ??
      null;
    if (server) used.add(server.meeting_id);
    return toEntry(local, server);
  });
  for (const item of items) {
    if (!used.has(item.meeting_id)) entries.push(toEntry(null, item));
  }
  return entries.sort(byStartDesc);
};

/** Customer id of every object of the reference book. */
export type ObjectOwners = ReadonlyMap<number, number>;

export const buildObjectOwners = (
  projects: ProjectCustomer[],
): ObjectOwners => {
  const owners = new Map<number, number>();
  for (const customer of projects) {
    for (const object of customer.objects) owners.set(object.id, customer.id);
  }
  return owners;
};

/**
 * The customer of a meeting: its own, or (old data with an object only) the
 * owner of the object in the reference book. `null` means "no project".
 */
export const resolveCustomerId = (
  entry: LibraryEntry,
  owners: ObjectOwners,
): number | null => {
  if (entry.customerId !== null) return entry.customerId;
  return entry.objectId !== null ? (owners.get(entry.objectId) ?? null) : null;
};

export const matchesFilter = (
  entry: LibraryEntry,
  filter: ProjectFilter,
  owners: ObjectOwners,
): boolean => {
  const customerId = resolveCustomerId(entry, owners);
  switch (filter.kind) {
    case "all":
      return true;
    case "none":
      return customerId === null;
    case "customer":
      return customerId === filter.customerId;
    case "object":
      return (
        customerId === filter.customerId && entry.objectId === filter.objectId
      );
  }
};

export interface ProjectObjectNode {
  id: number;
  name: string;
  count: number;
}

export interface ProjectNode {
  id: number;
  name: string;
  count: number;
  objects: ProjectObjectNode[];
}

/** Folders with meetings first (most meetings first), the empty ones after. */
const byCountThenName = (
  a: { name: string; count: number },
  b: { name: string; count: number },
): number => {
  if (a.count > 0 !== b.count > 0) return a.count > 0 ? -1 : 1;
  return b.count - a.count || a.name.localeCompare(b.name);
};

/**
 * The reference book of the site plus the projects met only in the meetings
 * (e.g. set offline), each with the number of meetings.
 */
export const buildProjectTree = (
  projects: ProjectCustomer[],
  entries: LibraryEntry[],
): ProjectNode[] => {
  const nodes = new Map<number, ProjectNode>();
  const ensureCustomer = (id: number, name: string): ProjectNode => {
    const existing = nodes.get(id);
    if (existing) return existing;
    const node: ProjectNode = { id, name, count: 0, objects: [] };
    nodes.set(id, node);
    return node;
  };
  const ensureObject = (
    customer: ProjectNode,
    id: number,
    name: string,
  ): ProjectObjectNode => {
    const existing = customer.objects.find((o) => o.id === id);
    if (existing) return existing;
    const node: ProjectObjectNode = { id, name, count: 0 };
    customer.objects.push(node);
    return node;
  };

  for (const customer of projects) {
    const node = ensureCustomer(customer.id, customer.name);
    for (const object of customer.objects) {
      ensureObject(node, object.id, object.name);
    }
  }
  const owners = buildObjectOwners(projects);
  for (const entry of entries) {
    const customerId = resolveCustomerId(entry, owners);
    if (customerId === null) continue;
    const customer = ensureCustomer(
      customerId,
      entry.customerName ?? String(customerId),
    );
    customer.count += 1;
    if (entry.objectId !== null) {
      ensureObject(
        customer,
        entry.objectId,
        entry.objectName ?? String(entry.objectId),
      ).count += 1;
    }
  }
  const nodesList = [...nodes.values()];
  for (const customer of nodesList) customer.objects.sort(byCountThenName);
  return nodesList.sort(byCountThenName);
};

/** "Customer · Object", or just the customer; empty without a project. */
export const projectLabel = (
  customerName: string | null,
  objectName: string | null,
): string =>
  [customerName, objectName]
    .filter((part): part is string => !!part)
    .join(" · ");

export interface DayGroup {
  key: string;
  /** `null` for the meetings without a date. */
  date: Date | null;
  entries: LibraryEntry[];
}

const dayKey = (date: Date): string =>
  `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;

/** Entries must already be sorted newest first. */
export const groupByDay = (entries: LibraryEntry[]): DayGroup[] => {
  const groups: DayGroup[] = [];
  for (const entry of entries) {
    const date = entry.startedAt ? new Date(entry.startedAt) : null;
    const valid = date && !Number.isNaN(date.getTime()) ? date : null;
    const key = valid ? dayKey(valid) : "none";
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.entries.push(entry);
    } else {
      groups.push({ key, date: valid, entries: [entry] });
    }
  }
  return groups;
};

/** "Сегодня" / "Вчера" / "21 октября" (with the year for other years). */
export const formatDayLabel = (
  date: Date,
  now: Date,
  locale: string,
  labels: { today: string; yesterday: string },
): string => {
  const key = dayKey(date);
  if (key === dayKey(now)) return labels.today;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (key === dayKey(yesterday)) return labels.yesterday;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  }).format(date);
};

export interface SnippetPart {
  text: string;
  match: boolean;
}

/** Splits a search snippet: the found words are wrapped in `[` `]`. */
export const splitSnippet = (snippet: string): SnippetPart[] => {
  const parts: SnippetPart[] = [];
  const pattern = /\[([^\]]*)\]/g;
  let last = 0;
  for (const found of snippet.matchAll(pattern)) {
    const index = found.index ?? 0;
    if (index > last)
      parts.push({ text: snippet.slice(last, index), match: false });
    if (found[1]) parts.push({ text: found[1], match: true });
    last = index + found[0].length;
  }
  if (last < snippet.length) {
    parts.push({ text: snippet.slice(last), match: false });
  }
  return parts;
};

export type EntryStatusKind =
  | "recording"
  | "interrupted"
  | "pending"
  | "sending"
  | "error"
  | "empty"
  | "onServer"
  | "protocolReady";

/**
 * The one status shown on a card. `syncingId` is the local meeting that is
 * being uploaded right now.
 */
export const getEntryStatus = (
  entry: LibraryEntry,
  syncingId: string | null,
): EntryStatusKind => {
  const { local, server } = entry;
  if (local) {
    if (local.status === "recording") return "recording";
    if (local.status === "interrupted") return "interrupted";
    if (local.sync_state === "error") return "error";
    if (local.sync_state === "empty") return "empty";
  }
  if (server) return server.protocol_ready ? "protocolReady" : "onServer";
  return local && syncingId === local.id ? "sending" : "pending";
};

/** The local meeting a site meeting belongs to, if it was recorded here. */
export const findLocalForServer = (
  locals: MeetingInfo[],
  items: LibraryItem[],
  serverMeetingId: number,
): MeetingInfo | null => {
  const clientUuid = items.find(
    (item) => item.meeting_id === serverMeetingId,
  )?.client_uuid;
  return (
    locals.find(
      (m) =>
        m.server_meeting_id === serverMeetingId ||
        (clientUuid !== null &&
          clientUuid !== undefined &&
          m.id === clientUuid),
    ) ?? null
  );
};
