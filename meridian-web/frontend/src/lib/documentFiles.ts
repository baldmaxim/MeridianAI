// Утилиты по файлам документов (чистые функции, без сети и сторонних библиотек).

export const DOCUMENT_ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.xlsx', '.txt', '.md', '.csv'];

/** Расширение файла в нижнем регистре, включая точку: "Отчёт.PDF" → ".pdf". Без расширения → "". */
export function getFileExtension(filename: string): string {
  const i = filename.lastIndexOf('.');
  if (i <= 0 || i === filename.length - 1) return '';
  return filename.slice(i).toLowerCase();
}

/** Поддерживается ли файл по расширению (case-insensitive). */
export function isSupportedDocumentFile(file: File): boolean {
  return DOCUMENT_ALLOWED_EXTENSIONS.includes(getFileExtension(file.name));
}

function round1(n: number): number {
  return n >= 100 ? Math.round(n) : Math.round(n * 10) / 10;
}

/** Человекочитаемый размер: 950 Б · 1.2 МБ · 12.4 МБ. */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} Б`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${round1(kb)} КБ`;
  const mb = kb / 1024;
  if (mb < 1024) return `${round1(mb)} МБ`;
  return `${round1(mb / 1024)} ГБ`;
}

/** Стабильный ключ элемента очереди (name+size+lastModified+random) для React key. */
export function makeUploadClientId(file: File): string {
  const rand = Math.random().toString(36).slice(2, 8);
  return `${file.name}:${file.size}:${file.lastModified}:${rand}`;
}
