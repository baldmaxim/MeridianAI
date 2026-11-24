import { describe, expect, it } from 'vitest';
import {
  buildMergeLayout, clampSheetRange, columnLabel, decodeText, getPreviewKind,
  isTooLargeForPreview, normalizeSheetRows, PREVIEW_MAX_BYTES,
} from './documentPreview';

describe('getPreviewKind', () => {
  it.each([
    ['.pdf', 'pdf'], ['PDF', 'pdf'], ['.PDF', 'pdf'], ['.docx', 'docx'], ['.xlsx', 'xlsx'],
    ['.csv', 'csv'], ['.txt', 'text'], ['.MD', 'text'],
  ])('%s → %s', (ext, kind) => {
    expect(getPreviewKind(ext)).toBe(kind);
  });

  it.each([null, undefined, '', '.doc', '.xls', '.zip', '.constructor'])('%s → null', (ext) => {
    expect(getPreviewKind(ext)).toBeNull();
  });
});

describe('isTooLargeForPreview', () => {
  it('граница 25 МБ и неизвестный размер', () => {
    expect(isTooLargeForPreview(PREVIEW_MAX_BYTES)).toBe(false);
    expect(isTooLargeForPreview(PREVIEW_MAX_BYTES + 1)).toBe(true);
    expect(isTooLargeForPreview(null)).toBe(false);
    expect(isTooLargeForPreview(undefined)).toBe(false);
  });
});

describe('decodeText', () => {
  it('UTF-8 (с BOM и без)', () => {
    const utf8 = new TextEncoder().encode('Договор №1');
    expect(decodeText(utf8.buffer as ArrayBuffer)).toBe('Договор №1');
    const bom = new Uint8Array([0xef, 0xbb, 0xbf, ...utf8]);
    expect(decodeText(bom.buffer)).toBe('Договор №1');
  });

  it('не UTF-8 → windows-1251', () => {
    // «Привет» в cp1251
    const cp1251 = new Uint8Array([0xcf, 0xf0, 0xe8, 0xe2, 0xe5, 0xf2]);
    expect(decodeText(cp1251.buffer)).toBe('Привет');
  });
});

describe('columnLabel', () => {
  it('A…Z, AA, AB, AZ, BA, ZZ, AAA', () => {
    expect([0, 1, 25, 26, 27, 51, 52, 701, 702].map(columnLabel)).toEqual(
      ['A', 'B', 'Z', 'AA', 'AB', 'AZ', 'BA', 'ZZ', 'AAA'],
    );
  });
});

describe('clampSheetRange', () => {
  it('маленький лист не режется', () => {
    const r = clampSheetRange({ s: { r: 0, c: 0 }, e: { r: 9, c: 4 } });
    expect(r.range.e).toEqual({ r: 9, c: 4 });
    expect(r.truncatedRows || r.truncatedCols).toBe(false);
    expect([r.totalRows, r.totalCols]).toEqual([10, 5]);
  });

  it('«мусорный» диапазон режется лимитами, начало сохраняется', () => {
    const r = clampSheetRange({ s: { r: 3, c: 2 }, e: { r: 1048575, c: 16383 } });
    expect(r.range).toEqual({ s: { r: 3, c: 2 }, e: { r: 3 + 1999, c: 2 + 99 } });
    expect(r.truncatedRows).toBe(true);
    expect(r.truncatedCols).toBe(true);
    expect(r.totalRows).toBe(1048573);
  });
});

describe('normalizeSheetRows', () => {
  it('дополняет и приводит к строкам', () => {
    expect(normalizeSheetRows([['a', 1], [], [null, undefined, 'x']], 3)).toEqual([
      ['a', '1', ''], ['', '', ''], ['', '', 'x'],
    ]);
  });
});

describe('buildMergeLayout', () => {
  it('colSpan/rowSpan и закрытые ячейки', () => {
    const l = buildMergeLayout([{ s: { r: 0, c: 0 }, e: { r: 1, c: 2 } }], { r: 0, c: 0 }, 5, 5);
    expect(l.spans.get('0,0')).toEqual({ rowSpan: 2, colSpan: 3 });
    expect(l.covered.size).toBe(5);
    expect(l.covered.has('1,2')).toBe(true);
    expect(l.covered.has('0,0')).toBe(false);
  });

  it('смещение окна, обрезка по границе, одиночные и внешние пропускаются', () => {
    const l = buildMergeLayout(
      [
        { s: { r: 5, c: 1 }, e: { r: 9, c: 9 } }, // начинается в окне, выходит за край
        { s: { r: 0, c: 0 }, e: { r: 1, c: 1 } }, // до начала окна
        { s: { r: 6, c: 1 }, e: { r: 6, c: 1 } }, // одна ячейка
      ],
      { r: 4, c: 1 }, 3, 3,
    );
    expect(l.spans.get('1,0')).toEqual({ rowSpan: 2, colSpan: 3 });
    expect(l.spans.size).toBe(1);
  });

  it('без merges — пусто', () => {
    const l = buildMergeLayout(undefined, { r: 0, c: 0 }, 3, 3);
    expect(l.spans.size + l.covered.size).toBe(0);
  });
});
