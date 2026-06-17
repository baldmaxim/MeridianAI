import api from './client';

export type RagFolderStatus = 'ready' | 'indexing' | 'error' | 'disabled';

export interface RagFolderApi {
  id: number;
  title: string;
  description: string | null;
  customer_id: number | null;
  object_id: number | null;
  path: string[];
  documents_count: number;
  chunks_count: number;
  updated_at: string;
  status: RagFolderStatus;
  status_label: string | null;
  disabled: boolean;
}

export interface RagAttachedFolderApi {
  source_id: number;
  folder_id: number;
  title: string;
  description: string | null;
  path: string[];
  documents_count: number;
  chunks_count: number;
  updated_at: string;
  status: RagFolderStatus;
  status_label: string | null;
  disabled: boolean;
  included: boolean;
  priority: number;
}

export interface RagFolderCreateApi {
  title: string;
  description?: string | null;
  customer_id?: number | null;
  object_id?: number | null;
  path?: string[];
  status?: RagFolderStatus;
  metadata_json?: string | null;
}

export interface RagFolderUpdateApi {
  title?: string | null;
  description?: string | null;
  customer_id?: number | null;
  object_id?: number | null;
  path?: string[] | null;
  status?: RagFolderStatus | null;
  metadata_json?: string | null;
}

export interface RagFolderDocumentApi {
  id: number;
  folder_id: number;
  document_id: number;
  original_name: string;
  file_ext: string | null;
  status: string;
  chunks_count: number;
  created_at: string;
}

// ── папки ─────────────────────────────────────────────────────────────────────

export async function listRagFolders(params?: {
  customer_id?: number | null;
  object_id?: number | null;
  q?: string;
  limit?: number;
}): Promise<RagFolderApi[]> {
  const query: Record<string, string | number> = {};
  if (params?.customer_id != null) query.customer_id = params.customer_id;
  if (params?.object_id != null) query.object_id = params.object_id;
  if (params?.q) query.q = params.q;
  if (params?.limit != null) query.limit = params.limit;
  const { data } = await api.get<RagFolderApi[]>('/rag/folders', { params: query });
  return data;
}

export async function createRagFolder(body: RagFolderCreateApi): Promise<RagFolderApi> {
  const { data } = await api.post<RagFolderApi>('/rag/folders', body);
  return data;
}

export async function updateRagFolder(folderId: number, body: RagFolderUpdateApi): Promise<RagFolderApi> {
  const { data } = await api.patch<RagFolderApi>(`/rag/folders/${folderId}`, body);
  return data;
}

export async function deleteRagFolder(folderId: number): Promise<void> {
  await api.delete(`/rag/folders/${folderId}`);
}

// ── документы папки ───────────────────────────────────────────────────────────

export async function listRagFolderDocuments(folderId: number): Promise<RagFolderDocumentApi[]> {
  const { data } = await api.get<RagFolderDocumentApi[]>(`/rag/folders/${folderId}/documents`);
  return data;
}

export async function attachDocumentToRagFolder(folderId: number, documentId: number): Promise<RagFolderDocumentApi> {
  const { data } = await api.post<RagFolderDocumentApi>(`/rag/folders/${folderId}/documents`, { document_id: documentId });
  return data;
}

export async function detachDocumentFromRagFolder(folderId: number, documentId: number): Promise<void> {
  await api.delete(`/rag/folders/${folderId}/documents/${documentId}`);
}

// ── подключение к встрече ─────────────────────────────────────────────────────

export async function listMeetingRagFolders(meetingId: number): Promise<RagAttachedFolderApi[]> {
  const { data } = await api.get<RagAttachedFolderApi[]>(`/meetings/${meetingId}/rag-folders`);
  return data;
}

export async function attachMeetingRagFolder(
  meetingId: number,
  folderId: number,
  body?: { included?: boolean; priority?: number },
): Promise<RagAttachedFolderApi> {
  const { data } = await api.post<RagAttachedFolderApi>(`/meetings/${meetingId}/rag-folders`, {
    folder_id: folderId,
    ...(body ?? {}),
  });
  return data;
}

export async function updateMeetingRagFolder(
  meetingId: number,
  sourceId: number,
  body: { included?: boolean; priority?: number },
): Promise<RagAttachedFolderApi> {
  const { data } = await api.patch<RagAttachedFolderApi>(`/meetings/${meetingId}/rag-folders/${sourceId}`, body);
  return data;
}

export async function detachMeetingRagFolder(meetingId: number, sourceId: number): Promise<void> {
  await api.delete(`/meetings/${meetingId}/rag-folders/${sourceId}`);
}
