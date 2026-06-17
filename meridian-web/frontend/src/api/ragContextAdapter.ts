import type {
  RagContextAdapter,
  RagFolderViewModel,
  RagAttachedFolderViewModel,
} from '../components/context/ragContextTypes';
import {
  listRagFolders, listMeetingRagFolders, attachMeetingRagFolder,
  updateMeetingRagFolder, detachMeetingRagFolder,
  type RagFolderApi, type RagAttachedFolderApi,
} from './rag';

function folderApiToVm(x: RagFolderApi): RagFolderViewModel {
  return {
    id: String(x.id),
    title: x.title,
    description: x.description ?? undefined,
    path: x.path,
    documentsCount: x.documents_count,
    chunksCount: x.chunks_count,
    updatedAt: x.updated_at,
    status: x.status,
    statusLabel: x.status_label ?? undefined,
    disabled: x.disabled,
  };
}

function attachedApiToVm(x: RagAttachedFolderApi): RagAttachedFolderViewModel {
  return {
    sourceId: String(x.source_id),
    folderId: String(x.folder_id),
    title: x.title,
    description: x.description ?? undefined,
    path: x.path,
    documentsCount: x.documents_count,
    chunksCount: x.chunks_count,
    updatedAt: x.updated_at,
    included: x.included,
    priority: x.priority,
    status: x.status,
    statusLabel: x.status_label ?? undefined,
    disabled: x.disabled,
  };
}

// frontend id (string) → backend id (number)
function toNumberId(value: string, label: string): number {
  const n = Number(value);
  if (!Number.isInteger(n)) throw new Error(`${label} некорректен`);
  return n;
}

// Настоящий adapter поверх backend RAG API (Этап 5).
export const ragContextApiAdapter: RagContextAdapter = {
  enabled: true,

  async listFolders(params) {
    const folders = await listRagFolders({
      customer_id: params?.customerId ?? null,
      object_id: params?.objectId ?? null,
      q: params?.query,
    });
    const mapped = folders.map(folderApiToVm);
    return { folders: mapped, total: mapped.length };
  },

  async listAttachedFolders(meetingId) {
    const rows = await listMeetingRagFolders(meetingId);
    return rows.map(attachedApiToVm);
  },

  async attachFolder(meetingId, folderId) {
    const row = await attachMeetingRagFolder(meetingId, toNumberId(folderId, 'folderId'));
    return attachedApiToVm(row);
  },

  async updateAttachedFolder(meetingId, sourceId, patch) {
    const row = await updateMeetingRagFolder(meetingId, toNumberId(sourceId, 'sourceId'), patch);
    return attachedApiToVm(row);
  },

  async detachFolder(meetingId, sourceId) {
    await detachMeetingRagFolder(meetingId, toNumberId(sourceId, 'sourceId'));
  },
};
