import { create } from "zustand";
import { commands, type LibrarySnapshot } from "@/bindings";
import type { ProjectFilter } from "@/lib/utils/library";

interface LibraryStore {
  snapshot: LibrarySnapshot | null;
  /** A request is in flight (the refresh icon spins). */
  loading: boolean;
  error: string | null;
  filter: ProjectFilter;
  /** The site meeting open read-only (no local copy). */
  openServerId: number | null;

  /** `refresh`: ask the server; otherwise the cache answers at once. */
  load: (refresh: boolean) => Promise<void>;
  /**
   * The automatic refresh (window focus, a timer): no spinner, nothing is
   * shown on failure, and nothing is asked while another request is in flight.
   */
  refreshQuietly: () => Promise<void>;
  setFilter: (filter: ProjectFilter) => void;
  openServer: (serverMeetingId: number) => void;
  closeServer: () => void;
}

/** Only the newest request may write the result: slow answers are dropped. */
let latestRequest = 0;
/** A quiet refresh is under way: another one would only repeat it. */
let quietInFlight = false;

export const useLibraryStore = create<LibraryStore>()((set, get) => ({
  snapshot: null,
  loading: false,
  error: null,
  filter: { kind: "all" },
  openServerId: null,

  load: async (refresh) => {
    const request = ++latestRequest;
    set({ loading: true });
    const result = await commands.libraryGet(refresh);
    if (request !== latestRequest) return;
    if (result.status === "ok") {
      set({ snapshot: result.data, loading: false, error: null });
    } else {
      set({ loading: false, error: result.error });
    }
  },

  refreshQuietly: async () => {
    if (get().loading || quietInFlight || document.hidden) return;
    quietInFlight = true;
    const request = ++latestRequest;
    try {
      const result = await commands.libraryGet(true);
      if (request !== latestRequest || result.status !== "ok") return;
      set({ snapshot: result.data, error: null });
    } finally {
      quietInFlight = false;
    }
  },

  setFilter: (filter) => set({ filter }),
  openServer: (serverMeetingId) => set({ openServerId: serverMeetingId }),
  closeServer: () => set({ openServerId: null }),
}));
