import { create } from "zustand";
import { commands, type AccountInfo, type SyncStatus } from "@/bindings";

interface SyncStore {
  account: AccountInfo | null;
  /** The account is known (the first `get_account` answered). */
  accountLoaded: boolean;
  status: SyncStatus | null;

  load: () => Promise<void>;
  setAccount: (account: AccountInfo | null) => void;
  setStatus: (status: SyncStatus) => void;
  /** Starts a pass over the queue now. */
  syncNow: () => Promise<void>;
}

export const useSyncStore = create<SyncStore>()((set) => ({
  account: null,
  accountLoaded: false,
  status: null,

  load: async () => {
    const [account, status] = await Promise.all([
      commands.getAccount(),
      commands.getSyncStatus(),
    ]);
    set({ account, accountLoaded: true, status });
  },

  setAccount: (account) => set({ account, accountLoaded: true }),
  setStatus: (status) => set({ status }),

  syncNow: async () => {
    await commands.syncNow();
  },
}));
