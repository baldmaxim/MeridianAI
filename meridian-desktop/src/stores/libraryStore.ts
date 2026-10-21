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
  setFilter: (filter: ProjectFilter) => void;
  openServer: (serverMeetingId: number) => void;
  closeServer: () => void;
}

/** Only the newest request may write the result: slow answers are dropped. */
let latestRequest = 0;

export const useLibraryStore = create<LibraryStore>()((set) => ({
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

  setFilter: (filter) => set({ filter }),
  openServer: (serverMeetingId) => set({ openServerId: serverMeetingId }),
  closeServer: () => set({ openServerId: null }),
}));
