import { useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';
import {
  buildMergeLayout, clampSheetRange, columnLabel, decodeText, normalizeSheetRows,
  SHEET_MAX_COLS, SHEET_MAX_ROWS,
  type ICellRange, type IMergeLayout,
} from '../../lib/documentPreview';
import viewer from './Viewer.module.css';
import styles from './SheetViewer.module.css';

interface ISheetView {
  name: string;
  rows: string[][];
  cols: number;
  layout: IMergeLayout;
  truncatedRows: boolean;
  truncatedCols: boolean;
}

interface ISheetViewerProps {
  data: ArrayBuffer;
  /** csv — единственный «лист» из текста; xlsx — книга с вкладками. */
  kind: 'xlsx' | 'csv';
  onError: (message: string) => void;
}

/** Книга → листы для показа. Тяжёлый xlsx подгружается динамически. */
const parseWorkbook = async (data: ArrayBuffer, kind: 'xlsx' | 'csv'): Promise<ISheetView[]> => {
  const XLSX = await import('xlsx');
  const wb = kind === 'csv'
    // csv: свой декодер (utf-8 → cp1251); raw — значения остаются текстом (ИНН, номера с ведущими нулями)
    ? XLSX.read(decodeText(data), { type: 'string', raw: true, sheetRows: SHEET_MAX_ROWS + 1 })
    // sheetRows: лишние строки не разбираем (12 МБ-лист: 10 с → 4 с); 2001-я строка = признак «обрезано»
    : XLSX.read(data, { type: 'array', cellFormula: false, cellHTML: false, sheetRows: SHEET_MAX_ROWS + 1 });
  return wb.SheetNames.map((name): ISheetView => {
    const ws = wb.Sheets[name];
    const ref = ws['!ref'];
    if (!ref) {
      return { name, rows: [], cols: 0, layout: { spans: new Map(), covered: new Set() }, truncatedRows: false, truncatedCols: false };
    }
    // окно якорим в A1 (как в Excel): буквы колонок и номера строк совпадают с адресами ячеек,
    // даже если данные начинаются, например, с B5
    const full = XLSX.utils.decode_range(ref);
    const clamped = clampSheetRange({ s: { r: 0, c: 0 }, e: full.e });
    // range режет разбор до лимитов: «раздутый» !ref (до XFD1048576) не вешает вкладку
    const aoa = XLSX.utils.sheet_to_json<unknown[]>(ws, {
      header: 1, raw: false, defval: '', blankrows: true, range: clamped.range,
    });
    const cols = clamped.range.e.c - clamped.range.s.c + 1;
    const rows = normalizeSheetRows(aoa, cols);
    const merges: ICellRange[] | undefined = ws['!merges'];
    return {
      name,
      rows,
      cols,
      layout: buildMergeLayout(merges, clamped.range.s, rows.length, cols),
      truncatedRows: clamped.truncatedRows,
      truncatedCols: clamped.truncatedCols,
    };
  });
};

interface ISheetTableProps {
  sheet: ISheetView;
}

const SheetTable: FC<ISheetTableProps> = ({ sheet }) => {
  const { rows, cols, layout } = sheet;
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th className={styles.corner} />
          {Array.from({ length: cols }, (_, c) => (
            <th key={c} className={styles.colHead}>{columnLabel(c)}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, r) => (
          <tr key={r}>
            <th className={styles.rowHead}>{r + 1}</th>
            {row.map((cell, c) => {
              const key = `${r},${c}`;
              if (layout.covered.has(key)) return null;
              const span = layout.spans.get(key);
              return (
                <td key={c} rowSpan={span?.rowSpan} colSpan={span?.colSpan}>{cell}</td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
};

/** .xlsx / .csv: таблица только через React (никакого HTML из SheetJS), вкладки листов, липкие шапки. */
export const SheetViewer: FC<ISheetViewerProps> = ({ data, kind, onError }) => {
  const [sheets, setSheets] = useState<ISheetView[] | null>(null);
  const [active, setActive] = useState(0);

  useEffect(() => {
    let cancelled = false;
    parseWorkbook(data, kind)
      .then((s) => {
        if (cancelled) return;
        setSheets(s);
        setActive(0);
      })
      .catch(() => {
        if (!cancelled) onError('Не удалось открыть таблицу');
      });
    return () => { cancelled = true; };
  }, [data, kind, onError]);

  const sheet = sheets?.[active];
  const table = useMemo(() => (sheet ? <SheetTable sheet={sheet} /> : null), [sheet]);

  if (!sheets) return null;
  return (
    <div className={styles.root}>
      {sheets.length > 1 && (
        <div className={styles.tabs} role="tablist">
          {sheets.map((s, i) => (
            <button
              key={`${i}-${s.name}`}
              type="button"
              role="tab"
              aria-selected={i === active}
              className={`${styles.tab} ${i === active ? styles.tabActive : ''}`.trim()}
              onClick={() => setActive(i)}
              title={s.name}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
      {sheet && (sheet.truncatedRows || sheet.truncatedCols) && (
        <div className={styles.note}>
          Показаны первые {[
            sheet.truncatedRows ? `${SHEET_MAX_ROWS} строк` : '',
            sheet.truncatedCols ? `${SHEET_MAX_COLS} колонок` : '',
          ].filter(Boolean).join(' и ')} — скачайте файл целиком
        </div>
      )}
      <div className={viewer.scroll}>
        {sheet && sheet.rows.length === 0 ? <div className={viewer.centerMsg}>Лист пуст</div> : table}
      </div>
    </div>
  );
};
