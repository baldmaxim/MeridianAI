import api from './client';

export interface BatchJob {
  id: number;
  status: string;
  original_filename: string;
  original_size: number;
  compressed_size: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface BatchJobDetail extends BatchJob {
  transcription_text: string | null;
  protocol_markdown: string | null;
  protocol_json: string | null;
}

/** Прямой PUT в S3 по presigned URL (§15) — без авторизации, с прогрессом. */
function putToS3(url: string, file: File, onProgress?: (frac: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
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
    xhr.send(file);
  });
}

export interface BatchUploadOpts {
  /** Задача 5: привязать дозапись офлайн-«дыры» к встрече */
  meetingId?: number;
  /** "gap_fill" — дозапись после обрыва связи (вливается в транскрипт встречи, без протокола) */
  kind?: 'gap_fill';
}

export async function uploadBatchAudio(
  file: File,
  onProgress?: (frac: number) => void,
  opts?: BatchUploadOpts
): Promise<BatchJob> {
  try {
    // 1. upload session → presigned URL (§15)
    const { data: session } = await api.post('/batch/upload-session', {
      filename: file.name,
      size: file.size,
      meeting_id: opts?.meetingId,
      kind: opts?.kind,
    });
    // 2. прямая загрузка в S3
    await putToS3(session.upload_url, file, onProgress);
    // 3. подтверждение → создаёт задачу обработки
    const { data } = await api.post(`/batch/confirm/${session.file_id}`, {
      meeting_id: opts?.meetingId,
      kind: opts?.kind,
    });
    return data;
  } catch (e: any) {
    // S3 не настроен → fallback на загрузку через backend
    if (e?.response?.status === 503) {
      const form = new FormData();
      form.append('file', file);
      if (opts?.meetingId != null) form.append('meeting_id', String(opts.meetingId));
      if (opts?.kind) form.append('kind', opts.kind);
      const { data } = await api.post('/batch/upload', form);
      return data;
    }
    throw e;
  }
}

export async function getBatchJobs(): Promise<BatchJob[]> {
  const { data } = await api.get('/batch/jobs');
  return data;
}

export async function getBatchJob(id: number): Promise<BatchJobDetail> {
  const { data } = await api.get(`/batch/jobs/${id}`);
  return data;
}

export async function deleteBatchJob(id: number): Promise<void> {
  await api.delete(`/batch/jobs/${id}`);
}

export async function downloadBatchResult(id: number, type: string): Promise<void> {
  const { data, headers } = await api.get(`/batch/jobs/${id}/download/${type}`, {
    responseType: 'blob',
  });
  const blob = new Blob([data]);
  const disposition = headers['content-disposition'] || '';
  const match = disposition.match(/filename="(.+?)"/);
  const filename = match ? match[1] : `download_${type}`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
