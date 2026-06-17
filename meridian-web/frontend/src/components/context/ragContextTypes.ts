// ── Frontend-контракт RAG-папок (этап 4) ──────────────────────────────────────
// Чистый UI-контракт без backend. Реальный adapter появится на этапе 5; пока
// по умолчанию используется disabledRagContextAdapter, который НЕ делает запросов.

export type RagFolderStatus =
  | 'ready'
  | 'indexing'
  | 'error'
  | 'disabled';

export interface RagFolderViewModel {
  id: string;
  title: string;
  description?: string;
  path?: string[];
  documentsCount?: number;
  chunksCount?: number;
  updatedAt?: string;
  status: RagFolderStatus;
  statusLabel?: string;
  disabled?: boolean;
}

export interface RagAttachedFolderViewModel {
  sourceId: string;
  folderId: string;
  title: string;
  description?: string;
  path?: string[];
  documentsCount?: number;
  chunksCount?: number;
  updatedAt?: string;
  included: boolean;
  priority?: number;
  status: RagFolderStatus;
  statusLabel?: string;
  disabled?: boolean;
  optimistic?: boolean;
}

export interface RagFolderListResult {
  folders: RagFolderViewModel[];
  total: number;
}

export interface RagContextAdapter {
  enabled: boolean;
  disabledReason?: string;

  listFolders: (params?: {
    query?: string;
    customerId?: number | null;
    objectId?: number | null;
  }) => Promise<RagFolderListResult>;

  listAttachedFolders: (meetingId: number) => Promise<RagAttachedFolderViewModel[]>;

  attachFolder: (
    meetingId: number,
    folderId: string,
  ) => Promise<RagAttachedFolderViewModel>;

  updateAttachedFolder: (
    meetingId: number,
    sourceId: string,
    patch: {
      included?: boolean;
      priority?: number;
    },
  ) => Promise<RagAttachedFolderViewModel>;

  detachFolder: (
    meetingId: number,
    sourceId: string,
  ) => Promise<void>;
}

const RAG_DISABLED_REASON = 'RAG-папки ещё не подключены';

// Заглушка-адаптер: никаких сетевых запросов. Списки пустые; мутации бросают
// понятную ошибку (UI до них не доходит, т.к. enabled=false).
export const disabledRagContextAdapter: RagContextAdapter = {
  enabled: false,
  disabledReason: RAG_DISABLED_REASON,
  listFolders: async () => ({ folders: [], total: 0 }),
  listAttachedFolders: async () => [],
  attachFolder: async () => { throw new Error(RAG_DISABLED_REASON); },
  updateAttachedFolder: async () => { throw new Error(RAG_DISABLED_REASON); },
  detachFolder: async () => { throw new Error(RAG_DISABLED_REASON); },
};
