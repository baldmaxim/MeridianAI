// Предпросмотр документов: чистые функции без тяжёлых библиотек (pdfjs/docx/xlsx грузятся лениво во вьюерах).
// Здесь — только типы и логика, безопасная для основного бандла.

export type PreviewKind = 'pdf' | 'docx' | 'xlsx' | 'csv' | 'text';

/** Больше этого размера файл в предпросмотр не грузим (байты, 25 МБ). */
export const PREVIEW_MAX_BYTES = 25 * 1024 * 1024;
/** Лимиты таблицы на лист. */
export const SHEET_MAX_ROWS = 2000;
export const SHEET_MAX_COLS = 100;

const KIND_BY_EXT: Record<string, PreviewKind> = {
  pdf: 'pdf',
  docx: 'docx',
  xlsx: 'xlsx',
  csv: 'csv',
  txt: 'text',
  md: 'text',
};

/** Вид предпросмотра по расширению (".PDF", "pdf" — оба подходят); null — предпросмотра нет. */
export function getPreviewKind(ext: string | null | undefined): PreviewKind | null {
  if (!ext) return null;
  const key = ext.trim().replace(/^\./, '').toLowerCase();
  return Object.hasOwn(KIND_BY_EXT, key) ? KIND_BY_EXT[key] : null;
}

/** Слишком ли большой файл для предпросмотра (неизвестный размер — пробуем). */
export function isTooLargeForPreview(fileSize: number | null | undefined): boolean {
  return fileSize != null && fileSize > PREVIEW_MAX_BYTES;
}

/** Текст из байтов: UTF-8 (строго), при ошибке — windows-1251 (старые txt/csv из Windows). */
export function decodeText(buffer: ArrayBuffer): string {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer);
  } catch {
    return new TextDecoder('windows-1251').decode(buffer);
  }
}

/** Буквенное имя колонки: 0 → A, 25 → Z, 26 → AA. */
export function columnLabel(index: number): string {
  let n = index + 1;
  let label = '';
  while (n > 0) {
    const rem = (n - 1) % 26;
    label = String.fromCharCode(65 + rem) + label;
    n = Math.floor((n - 1) / 26);
  }
  return label;
}

export interface ICellAddress {
  r: number;
  c: number;
}

export interface ICellRange {
  s: ICellAddress;
  e: ICellAddress;
}

export interface IClampedRange {
  range: ICellRange;
  totalRows: number;
  totalCols: number;
  truncatedRows: boolean;
  truncatedCols: boolean;
}

/** Обрезать диапазон листа лимитами строк/колонок (до разбора — «мусорный» !ref не вешает вкладку). */
export function clampSheetRange(
  ref: ICellRange,
  maxRows = SHEET_MAX_ROWS,
  maxCols = SHEET_MAX_COLS,
): IClampedRange {
  const totalRows = ref.e.r - ref.s.r + 1;
  const totalCols = ref.e.c - ref.s.c + 1;
  return {
    range: {
      s: { r: ref.s.r, c: ref.s.c },
      e: {
        r: ref.s.r + Math.min(totalRows, maxRows) - 1,
        c: ref.s.c + Math.min(totalCols, maxCols) - 1,
      },
    },
    totalRows,
    totalCols,
    truncatedRows: totalRows > maxRows,
    truncatedCols: totalCols > maxCols,
  };
}

/** Строки листа (массив массивов от sheet_to_json) → прямоугольник строк-строк заданной ширины. */
export function normalizeSheetRows(aoa: readonly (readonly unknown[])[], cols: number): string[][] {
  return aoa.map((row) => {
    const out: string[] = [];
    for (let c = 0; c < cols; c += 1) {
      const v = row[c];
      out.push(v == null ? '' : String(v));
    }
    return out;
  });
}

export interface IMergeLayout {
  /** «строка,колонка» якорной ячейки → размеры объединения. */
  spans: Map<string, { rowSpan: number; colSpan: number }>;
  /** Ячейки, закрытые объединением (кроме якорной) — не рендерятся. */
  covered: Set<string>;
}

/**
 * Объединённые ячейки (!merges) → colSpan/rowSpan в координатах показанного окна.
 * origin — левый верх окна в координатах листа; всё за пределами окна обрезается.
 */
export function buildMergeLayout(
  merges: readonly ICellRange[] | undefined,
  origin: ICellAddress,
  rows: number,
  cols: number,
): IMergeLayout {
  const spans = new Map<string, { rowSpan: number; colSpan: number }>();
  const covered = new Set<string>();
  for (const m of merges ?? []) {
    const r0 = m.s.r - origin.r;
    const c0 = m.s.c - origin.c;
    if (r0 < 0 || c0 < 0 || r0 >= rows || c0 >= cols) continue;
    const r1 = Math.min(m.e.r - origin.r, rows - 1);
    const c1 = Math.min(m.e.c - origin.c, cols - 1);
    const rowSpan = r1 - r0 + 1;
    const colSpan = c1 - c0 + 1;
    if (rowSpan === 1 && colSpan === 1) continue;
    spans.set(`${r0},${c0}`, { rowSpan, colSpan });
    for (let r = r0; r <= r1; r += 1) {
      for (let c = c0; c <= c1; c += 1) {
        if (r !== r0 || c !== c0) covered.add(`${r},${c}`);
      }
    }
  }
  return { spans, covered };
}
