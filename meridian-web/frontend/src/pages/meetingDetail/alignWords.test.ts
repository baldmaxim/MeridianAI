import { describe, it, expect } from 'vitest';
import { alignWordsToText } from './alignWords';

const w = (text: string, start: number) => ({ text, start, end: start + 0.4 });

describe('alignWordsToText', () => {
  it('1:1 — слова по порядку, пробелы сохранены без времени', () => {
    const tokens = alignWordsToText('Добрый день  всем', [w('Добрый', 0), w('день', 0.5), w('всем', 1)]);
    expect(tokens?.map((t) => t.text).join('')).toBe('Добрый день  всем');
    expect(tokens?.filter((t) => t.start !== null).map((t) => t.start)).toEqual([0, 0.5, 1]);
    expect(tokens?.find((t) => t.text === '  ')?.start).toBeNull();
  });

  it('пунктуация и регистр: «Привет,» ↔ «привет», ё ↔ е (число токенов не совпало)', () => {
    const tokens = alignWordsToText('Привет, всё хорошо.', [w('привет', 0), w('все', 0.5), w('хорошо', 1), w('да', 2)]);
    const timed = tokens?.filter((t) => t.start !== null) ?? [];
    expect(timed.map((t) => t.text)).toEqual(['Привет,', 'всё', 'хорошо.']);
    expect(timed.map((t) => t.start)).toEqual([0, 0.5, 1]);
  });

  it('вставленное слово остаётся без времени, остальные сопоставляются', () => {
    const tokens = alignWordsToText('мы очень рады вас видеть', [w('мы', 0), w('рады', 1), w('вас', 1.5), w('видеть', 2)]);
    const byText = Object.fromEntries((tokens ?? []).filter((t) => t.text.trim()).map((t) => [t.text, t.start]));
    expect(byText).toEqual({ мы: 0, очень: null, рады: 1, вас: 1.5, видеть: 2 });
  });

  it('перевод/исправленный текст — null', () => {
    expect(alignWordsToText('Здравствуйте, коллеги', [w('Merhaba', 0), w('arkadaşlar', 0.5), w('nasılsınız', 1)])).toBeNull();
  });

  it('нет слов — null', () => {
    expect(alignWordsToText('текст', null)).toBeNull();
    expect(alignWordsToText('текст', undefined)).toBeNull();
    expect(alignWordsToText('текст', [])).toBeNull();
  });
});
