import { describe, expect, it } from 'vitest';
import type { MeetingDocument } from '../../types';
import {
  buildTypeChips, countIncluded, filterByType, formatMetaLine, getDocTypeText,
  getPollInterval, getSourceStatus, groupBySource,
} from './sourcesModel';

const makeDoc = (over: Partial<MeetingDocument> = {}): MeetingDocument => ({
  id: 1,
  document_id: 1,
  original_name: 'file.pdf',
  file_ext: 'pdf',
  status: 'ready',
  included: true,
  priority: 0,
  chunks_count: 3,
  page_count: 1,
  sheet_count: null,
  processing_error: null,
  ...over,
});

describe('groupBySource', () => {
  it('группирует в порядке встреча/контрагент/объект и скрывает пустые', () => {
    const groups = groupBySource([
      makeDoc({ document_id: 1, source: 'object' }),
      makeDoc({ document_id: 2, source: 'meeting' }),
      makeDoc({ document_id: 3 }),
    ]);
    expect(groups.map((g) => g.source)).toEqual(['meeting', 'object']);
    expect(groups[0].docs.map((d) => d.document_id)).toEqual([2, 3]);
    expect(groups[0].title).toBe('Файлы встречи');
  });
});

describe('buildTypeChips / filterByType', () => {
  const docs = [
    makeDoc({ document_id: 1, doc_type: 'contract', doc_type_label: 'Договор' }),
    makeDoc({ document_id: 2, doc_type: 'letter', doc_type_label: 'Письмо' }),
    makeDoc({ document_id: 3, doc_type: 'contract', doc_type_label: 'Договор' }),
    makeDoc({ document_id: 4, doc_type: null }),
  ];
  const vocab = [{ key: 'letter', label: 'Письмо' }, { key: 'contract', label: 'Договор' }];

  it('считает только присутствующие типы в порядке словаря', () => {
    expect(buildTypeChips(docs, vocab)).toEqual([
      { key: 'letter', label: 'Письмо', count: 1 },
      { key: 'contract', label: 'Договор', count: 2 },
    ]);
  });

  it('фильтрует по типу; null — без фильтра', () => {
    expect(filterByType(docs, 'contract').map((d) => d.document_id)).toEqual([1, 3]);
    expect(filterByType(docs, null)).toHaveLength(4);
  });
});

describe('countIncluded', () => {
  it('считает включённые и всего', () => {
    expect(countIncluded([makeDoc({ included: true }), makeDoc({ included: false })])).toEqual({ included: 1, total: 2 });
  });
});

describe('getDocTypeText', () => {
  it('метка, «Определяется…» при обработке, иначе тире', () => {
    expect(getDocTypeText(makeDoc({ doc_type_label: 'Смета' }))).toBe('Смета');
    expect(getDocTypeText(makeDoc({ status: 'processing' }))).toBe('Определяется…');
    expect(getDocTypeText(makeDoc({ status: 'uploaded' }))).toBe('Определяется…');
    expect(getDocTypeText(makeDoc({ status: 'ready' }))).toBe('—');
  });
});

describe('getSourceStatus', () => {
  it('подписи статусов', () => {
    expect(getSourceStatus(makeDoc())).toBeNull();
    expect(getSourceStatus(makeDoc({ status: 'processing' }))?.label).toBe('Обработка');
    expect(getSourceStatus(makeDoc({ status: 'awaiting_ocr' }))?.label).toBe('Ждёт OCR');
    expect(getSourceStatus(makeDoc({ status: 'error', processing_error: 'сбой' }))).toEqual({
      kind: 'error', label: 'Ошибка', detail: 'сбой',
    });
  });
});

describe('getPollInterval', () => {
  it('быстро при обработке, редко при ожидании OCR, null когда всё готово', () => {
    expect(getPollInterval([makeDoc({ status: 'processing' })])).toBe(3000);
    expect(getPollInterval([makeDoc({ status: 'awaiting_ocr' })])).toBe(60000);
    expect(getPollInterval([makeDoc(), makeDoc({ status: 'error' })])).toBeNull();
  });
});

describe('formatMetaLine', () => {
  it('собирает строку и переводит ISO-дату', () => {
    expect(formatMetaLine({ number: '12', date: '2025-02-01', counterparty_name: 'ООО Ромашка' }))
      .toBe('№ 12 · от 01.02.2025 · ООО Ромашка');
    expect(formatMetaLine(null)).toBe('');
    expect(formatMetaLine({})).toBe('');
  });
});
