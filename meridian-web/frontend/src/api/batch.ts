import api from './client';
import { filenameFromDisposition, saveBlob } from './download';

export interface BatchJob {
  id: number;
  status: string;
  original_filename: string;
  original_size: number;
  compressed_size: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  /** Встреча, сделанная из этой записи (если сделана). */
  meeting_id: number | null;
}

export interface BatchToMeetingResult {
  meeting_id: number;
  title: string | null;
  segments_added: number;
  finalization_queued: boolean;
}

/**
 * Сделать встречу из готовой записи: транскрипт переносится во встречу и запускается
 * финализация — только она наполняет решения, поручения, риски и открытые вопросы.
 * Заказчик важен: без него особенности контрагента при извлечении знаний отбрасываются.
 */
export async function batchToMeeting(
  jobId: number,
  payload: { customer_id?: number | null; object_id?: number | null; title?: string | null },
): Promise<BatchToMeetingResult> {
  const { data } = await api.post(`/batch/jobs/${jobId}/to-meeting`, payload);
  return data;
}

export interface BatchSegment {
  speaker: string;
  start: number;
  end: number;
  text: string;
}

export interface BatchJobDetail extends BatchJob {
  transcription_text: string | null;
  protocol_markdown: string | null;
  protocol_json: string | null;
  segments: BatchSegment[];
}

/** Прямой PUT в S3 по presigned URL (§15) — без авторизации, с прогрессом. */
function putToS3(url: string, file: File, onProgress?: (frac: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { resolve(); return; }
      // 413 = лимит тела запроса на прокси перед хранилищем, а не проблема файла
      if (xhr.status === 413) {
        reject(new Error('Файл отклонён прокси хранилища (413): превышен лимит размера запроса.'));
        return;
      }
      reject(new Error(`Ошибка загрузки в хранилище (${xhr.status})`));
    };
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

/** Распознать уже загруженный в мини-облако аудиофайл (без повторной загрузки). */
export async function createBatchFromStash(fileId: number): Promise<BatchJob> {
  const { data } = await api.post(`/batch/from-stash/${fileId}`);
  return data;
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

export interface BatchAudioUrl {
  url: string;
  content_type: string | null;
  size: number | null;
}

/** Presigned-ссылка на исходное аудио задачи (проигрывание/скачивание). */
export async function getBatchAudioUrl(id: number): Promise<BatchAudioUrl> {
  const { data } = await api.get(`/batch/jobs/${id}/audio-url`);
  return data;
}

/** Скачать вырезанный фрагмент (mp3) — серверная нарезка ffmpeg. */
export async function downloadBatchClip(id: number, start: number, end: number): Promise<void> {
  const { data, headers } = await api.post(
    `/batch/jobs/${id}/clip`, { start, end }, { responseType: 'blob', timeout: 180_000 }
  );
  saveBlob(new Blob([data]), filenameFromDisposition(headers['content-disposition'], 'clip.mp3'));
}

/** Blob результата задачи (для «Скачать всё» в папку). */
export async function getBatchResultBlob(id: number, type: string): Promise<{ blob: Blob; filename: string }> {
  // таймаут: без него зависший запрос держит кнопку в состоянии «Скачивание…» бесконечно
  const { data, headers } = await api.get(`/batch/jobs/${id}/download/${type}`, {
    responseType: 'blob',
    timeout: 120_000,
  });
  return {
    blob: new Blob([data]),
    filename: filenameFromDisposition(headers['content-disposition'], type),
  };
}

export async function downloadBatchResult(id: number, type: string): Promise<void> {
  const { blob, filename } = await getBatchResultBlob(id, type);
  saveBlob(blob, filename);
}
