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

/** Шаг 2: прямой PUT в S3 по presigned URL (без auth, с прогрессом и поддержкой abort).
 *  Этап 22: headers (Content-Type + опц. SSE x-amz-*) приходят из upload-session — их обязан
 *  прислать браузер, если они подписаны. presigned URL НЕ логируем. */
export function putFileToPresignedUrl(
  url: string,
  file: File,
  headers?: Record<string, string>,
  onProgress?: (frac: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error('Загрузка отменена')); return; }
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    if (headers) {
      for (const [k, v] of Object.entries(headers)) {
        try { xhr.setRequestHeader(k, v); } catch { /* недопустимый заголовок — игнор */ }
      }
    }
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { resolve(); return; }
      // 403 обычно = права/подпись/CORS бакета; отдельный понятный текст оператору
      if (xhr.status === 403) {
        reject(new Error('Доступ к хранилищу отклонён (403). Проверьте права/CORS бакета.'));
        return;
      }
      reject(new Error(`Ошибка загрузки в хранилище (${xhr.status})`));
    };
    // CORS-блок/сетевой сбой даёт onerror (часто status 0) — не логируем URL, даём безопасный текст
    xhr.onerror = () =>
      reject(new Error('Не удалось загрузить файл напрямую в хранилище. Проверьте CORS/доступ к бакету.'));
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

/** Новый основной путь (Этап 4/22): presigned S3 upload → confirm → job обработки.
 *  При upload_mode=legacy_multipart (S3 выключен) — падаем на legacy multipart /documents/upload. */
export async function uploadDocumentPresigned(
  file: File,
  opts: DocumentUploadOpts = {},
  onProgress?: (frac: number) => void,
): Promise<{ document_id: number | null; mode: 's3_presigned' | 'legacy_multipart' }> {
  const session = await createDocumentUploadSession(file, opts);
  if (session.upload_mode === 'legacy_multipart' || !session.upload_url || session.document_id == null) {
    await uploadDocument(file, 'other');
    onProgress?.(1);
    return { document_id: null, mode: 'legacy_multipart' };
  }
  await putFileToPresignedUrl(session.upload_url, file, session.headers, onProgress);
  await confirmDocumentUpload(session.document_id);
  return { document_id: session.document_id, mode: 's3_presigned' };
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
