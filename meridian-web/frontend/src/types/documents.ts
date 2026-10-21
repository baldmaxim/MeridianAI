export interface DocumentInfo {
  filename: string;
  doc_type: string;
  doc_type_label: string;
  page_count: number;
}

// --- Этап 4: документы встречи на S3 ---

// awaiting_ocr — скан ждёт агента распознавания на компьютере с LM Studio (может ждать часами).
export type DocumentStatus = 'pending' | 'uploaded' | 'processing' | 'awaiting_ocr' | 'ready' | 'error';

export interface DocumentRecord {
  id: number;
  owner_user_id: number;
  customer_id: number | null;
  object_id: number | null;
  file_id: number | null;
  original_name: string;
  mime_type: string | null;
  file_ext: string;
  file_size: number | null;
  status: DocumentStatus;
  processing_error: string | null;
  page_count: number | null;
  sheet_count: number | null;
  created_by_user_id: number;
  created_at: string;
  updated_at: string;
  chunks_count: number;
}

export type DocumentUploadMode = 's3_presigned' | 'legacy_multipart';

export interface DocumentUploadSession {
  // Этап 22: mode-aware. legacy_multipart → грузим через legacy_upload_url; s3_presigned → PUT в S3.
  // upload_mode бэкенд шлёт всегда (default s3_presigned); остальные s3-поля отсутствуют в legacy.
  upload_mode: DocumentUploadMode;
  document_id?: number;
  file_id?: number;
  upload_url?: string;
  s3_key?: string;
  expires_in?: number;
  headers?: Record<string, string>;
  max_upload_bytes?: number;
  legacy_upload_url?: string;
}

export interface MeetingDocument {
  id: number;
  document_id: number;
  original_name: string;
  file_ext: string | null;
  status: DocumentStatus;
  included: boolean;
  priority: number;
  chunks_count: number;
  page_count: number | null;
  sheet_count: number | null;
  processing_error: string | null;
  ocr_note?: string | null;  // скан ждёт распознавания: идёт / компьютер не на связи N ч
  quality_note?: string | null;  // готовый скан: «Сверьте со сканом стр. 42, 74»
  ocr_missing_pages?: number[];  // страницы без текста — можно дораспознать
}

export interface DocumentChunkPreview {
  chunk_id: number;
  text: string;
  page_number: number | null;
  sheet_name: string | null;
}

export interface RelevantDocumentChunk {
  document_id: number;
  document_name: string;
  chunk_id: number;
  text: string;
  page_number: number | null;
  sheet_name: string | null;
  score: number;
}
