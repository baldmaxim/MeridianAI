/** Утилиты скачивания: имя из Content-Disposition (RFC 5987) и сохранение blob. */

/** Имя файла из Content-Disposition: сначала filename*=UTF-8'' , затем filename="". */
export function filenameFromDisposition(disposition: string | undefined, fallback: string): string {
  const cd = disposition || '';
  const ext = cd.match(/filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/);
  if (ext) {
    try {
      return decodeURIComponent(ext[1].trim());
    } catch {
      /* битая перкодировка — падаем на обычный filename */
    }
  }
  const plain = cd.match(/filename\s*=\s*"([^"]+)"/) || cd.match(/filename\s*=\s*([^;]+)/);
  return plain ? plain[1].trim() : fallback;
}

/** Сохранить blob как файл: ссылка в DOM + отложенный revoke (иначе Firefox/Safari рвут скачивание). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Текст ошибки из ответа с responseType: 'blob' (detail внутри blob, а не в data). */
export async function errorTextFromBlob(e: any, fallback: string): Promise<string> {
  const data = e?.response?.data;
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text());
      if (parsed?.detail) return String(parsed.detail);
    } catch {
      /* не JSON — отдаём фолбэк */
    }
  }
  return data?.detail || e?.message || fallback;
}

/** Скачать URL в blob с таймаутом (cross-origin S3 может «зависнуть» без него). */
export async function fetchBlob(url: string, timeoutMs = 180_000): Promise<Blob> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: ctrl.signal });
    if (!r.ok) throw new Error(`Хранилище ответило ${r.status}`);
    return await r.blob();
  } finally {
    clearTimeout(timer);
  }
}

/** Скачать по прямой ссылке силами браузера (без буферизации файла в памяти). */
export function saveUrl(url: string, filename: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename; // для cross-origin имя задаёт Content-Disposition сервера
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Ограничить ожидание промиса: зависший шаг не должен блокировать UI навсегда. */
export function withTimeout<T>(p: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${label}: превышено время ожидания`)), ms);
    p.then(resolve, reject).finally(() => clearTimeout(timer));
  });
}
