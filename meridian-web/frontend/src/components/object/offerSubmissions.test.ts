import { describe, expect, it } from 'vitest';
import type { DocumentRecord } from '../../types';
import { splitObjectDocuments, stripOfferPrefix } from './offerSubmissions';

const doc = (id: number, offer_submission?: string | null): DocumentRecord => ({
  id, offer_submission, original_name: `f${id}`,
} as DocumentRecord);

describe('stripOfferPrefix', () => {
  it('срезает «КП N · дата · папка · »', () => {
    const folder = '002 29.06.2026 Скидка';
    expect(
      stripOfferPrefix(`КП 321 · 2026-06-29 · ${folder} · Оферта строительство ЗУ 35 29.06.xlsx`, folder),
    ).toBe('Оферта строительство ЗУ 35 29.06.xlsx');
    expect(
      stripOfferPrefix('КП 330 · 2026-08-27 · 001 27.08.2026 · 1. Коммерческое предложение к Оферте 28.08.2026.pdf', '001 27.08.2026'),
    ).toBe('1. Коммерческое предложение к Оферте 28.08.2026.pdf');
  });

  it('без папки: «КП N · дата · » и «КП N · файл дата · »', () => {
    expect(stripOfferPrefix('КП 330 · 2026-08-27 · Смета.xlsx', '')).toBe('Смета.xlsx');
    expect(stripOfferPrefix('КП 330 · файл 2026-08-27 · Смета.xlsx', '')).toBe('Смета.xlsx');
  });

  it('папка со спецсимволами не ломает срез', () => {
    expect(stripOfferPrefix('КП 1 · 2026-01-02 · (a.b) · x.pdf', '(a.b)')).toBe('x.pdf');
  });

  it('формат не совпал — имя как есть', () => {
    expect(stripOfferPrefix('Договор.pdf', '')).toBe('Договор.pdf');
    expect(stripOfferPrefix('КП 321 · 2026-06-29 · другая папка · a.xlsx', '002 Скидка')).toBe(
      'КП 321 · 2026-06-29 · другая папка · a.xlsx',
    );
    expect(stripOfferPrefix('КП 321 · 2026-06-29 · ', '')).toBe('КП 321 · 2026-06-29 · ');
  });
});

describe('splitObjectDocuments', () => {
  it('делит на подачи и общий контекст, "" — отдельная корзина', () => {
    const { bySubmission, general } = splitObjectDocuments([
      doc(1, null), doc(2), doc(3, 'a'), doc(4, ''), doc(5, 'a'),
    ]);
    expect(general.map((d) => d.id)).toEqual([1, 2]);
    expect([...bySubmission.keys()]).toEqual(['a', '']);
    expect(bySubmission.get('a')?.map((d) => d.id)).toEqual([3, 5]);
    expect(bySubmission.get('')?.map((d) => d.id)).toEqual([4]);
  });
});
