import api from './client';
import type { DocumentInfo, DocumentRecord, DocumentUploadSession } from '../types';

export interface DocumentUploadOpts {
  customer_id?: number | null;
  object_id?: number | null;
}

/** Шаг 1: создать upload-session (presigned URL) для документа. */
export async function createDocumentUploadSession(
  file: File,
  opts: DocumentUploadOpts = {},
  signal?: AbortSignal,
): Promise<DocumentUploadSession> {
  const { data } = await api.post<DocumentUploadSession>('/documents/upload-session', {
    filename: file.name,
    content_type: file.type || null,
    size_bytes: file.size,
    customer_id: opts.customer_id ?? null,
    object_id: opts.object_id ?? null,
  }, { signal });
  return data;
}

/** Шаг 2: прямой PUT в S3 по presigned URL (без auth, с прогрессом и поддержкой abort). */
export function putFileToPresignedUrl(
  url: string,
  file: File,
  onProgress?: (frac: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error('Загрузка отменена')); return; }
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Ошибка загрузки в хранилище (${xhr.status})`));
    xhr.onerror = () => reject(new Error('Сбой сети при загрузке'));
    xhr.onabort = () => reject(new Error('Загрузка отменена'));
    if (signal) {
      const onAbort = () => xhr.abort();
      signal.addEventListener('abort', onAbort, { once: true });
      xhr.addEventListener('loadend', () => signal.removeEventListener('abort', onAbort), { once: true });
    }
    xhr.send(file);
  });
}

/** Шаг 3: подтвердить загрузку → backend запускает job обработки. */
export async function confirmDocumentUpload(documentId: number, signal?: AbortSignal): Promise<void> {
  await api.post(`/documents/${documentId}/confirm-upload`, undefined, { signal });
}

/** Новый основной путь (Этап 4): presigned S3 upload → confirm → job обработки. */
export async function uploadDocumentPresigned(
  file: File,
  opts: DocumentUploadOpts = {},
  onProgress?: (frac: number) => void,
): Promise<{ document_id: number }> {
  const session = await createDocumentUploadSession(file, opts);
  await putFileToPresignedUrl(session.upload_url, file, onProgress);
  await confirmDocumentUpload(session.document_id);
  return { document_id: session.document_id };
}

export interface DocumentFilters {
  customer_id?: number;
  object_id?: number;
  status?: string;
  q?: string;
}

export async function listDocumentRecords(filters?: DocumentFilters): Promise<DocumentRecord[]> {
  const params: Record<string, string | number> = {};
  if (filters?.customer_id != null) params.customer_id = filters.customer_id;
  if (filters?.object_id != null) params.object_id = filters.object_id;
  if (filters?.status) params.status = filters.status;
  if (filters?.q) params.q = filters.q;
  const { data } = await api.get<DocumentRecord[]>('/documents', { params });
  return data;
}

export async function getDocumentRecord(id: number): Promise<DocumentRecord> {
  const { data } = await api.get<DocumentRecord>(`/documents/${id}`);
  return data;
}

export async function deleteDocumentRecord(id: number): Promise<void> {
  await api.delete(`/documents/${id}`);
}

// --- Legacy (DEPRECATED) in-memory session docs ---

export async function uploadDocument(file: File, docType: string): Promise<DocumentInfo> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('doc_type', docType);
  const { data } = await api.post<DocumentInfo>('/documents/upload', formData);
  return data;
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const { data } = await api.get<DocumentInfo[]>('/documents/session-docs');
  return data;
}

export async function removeDocument(filename: string): Promise<void> {
  await api.delete(`/documents/session-docs/${encodeURIComponent(filename)}`);
}
