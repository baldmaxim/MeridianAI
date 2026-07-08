import api from './client';

export interface StashFile {
  id: number;
  original_name: string;
  size: number | null;
  mime: string | null;
  created_at: string;
  expires_at: string | null;
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

/** Загрузить файл в мини-облако: session → прямой PUT в S3 → confirm. */
export async function uploadStashFile(
  file: File,
  onProgress?: (frac: number) => void
): Promise<StashFile> {
  const { data: session } = await api.post('/stash/upload-session', {
    filename: file.name,
    size: file.size,
  });
  await putToS3(session.upload_url, file, onProgress);
  const { data } = await api.post(`/stash/confirm/${session.file_id}`);
  return data;
}

export async function getStashFiles(): Promise<StashFile[]> {
  const { data } = await api.get('/stash');
  return data;
}

export async function deleteStashFile(id: number): Promise<void> {
  await api.delete(`/stash/${id}`);
}

/** Скачать оригинал: получить presigned GET URL и запустить скачивание (attachment). */
export async function downloadStashFile(id: number): Promise<void> {
  const { data } = await api.get(`/stash/${id}/download-url`);
  const a = document.createElement('a');
  a.href = data.url; // presigned URL — не логировать
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
