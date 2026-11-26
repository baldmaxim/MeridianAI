import type { TranscriptWordTiming } from '../../types';

export interface IAlignedToken {
  text: string;
  start: number | null;
  end: number | null;
}

/** Сколько следующих непросмотренных слов проверяем при расхождении числа токенов. */
const LOOKAHEAD = 3;
/** Минимальная доля сопоставленных токенов — иначе текст считаем изменённым. */
const MIN_MATCH_RATIO = 0.6;

const isSpace = (token: string): boolean => /^\s+$/.test(token);

/** Сравнимая форма: нижний регистр, только буквы/цифры, ё → е. */
const normalize = (value: string): string =>
  value.toLowerCase().replace(/ё/g, 'е').replace(/[^\p{L}\p{N}]/gu, '');

/**
 * Сопоставляет токены показываемого текста (с пробелами) словам с таймкодами.
 * null — слов нет или текст не похож на распознанный (исправлен/переведён): подсветка не нужна.
 */
export const alignWordsToText = (
  text: string,
  words: TranscriptWordTiming[] | null | undefined,
): IAlignedToken[] | null => {
  if (!words || words.length === 0) return null;
  const tokens = text.split(/(\s+)/).filter((token) => token !== '');
  const wordTokens = tokens.filter((token) => !isSpace(token));
  if (wordTokens.length === 0) return null;

  const result: IAlignedToken[] = [];

  // Число совпало — сопоставляем по порядку, как есть
  if (wordTokens.length === words.length) {
    let w = 0;
    for (const token of tokens) {
      if (isSpace(token)) {
        result.push({ text: token, start: null, end: null });
      } else {
        result.push({ text: token, start: words[w].start, end: words[w].end });
        w += 1;
      }
    }
    return result;
  }

  // Иначе — жадно, по нормализованной форме; несовпавшие токены без времени
  const normalizedWords = words.map((word) => normalize(word.text));
  let pointer = 0;
  let comparable = 0;
  let matched = 0;
  for (const token of tokens) {
    if (isSpace(token)) {
      result.push({ text: token, start: null, end: null });
      continue;
    }
    const form = normalize(token);
    let found = -1;
    if (form !== '') {
      comparable += 1;
      const limit = Math.min(pointer + LOOKAHEAD, words.length);
      for (let j = pointer; j < limit; j += 1) {
        if (normalizedWords[j] === form) {
          found = j;
          break;
        }
      }
    }
    if (found === -1) {
      result.push({ text: token, start: null, end: null });
    } else {
      matched += 1;
      pointer = found + 1;
      result.push({ text: token, start: words[found].start, end: words[found].end });
    }
  }
  // Токены из одной пунктуации («—») в долю не входят: у них нет формы для сравнения
  if (comparable === 0 || matched / comparable < MIN_MATCH_RATIO) return null;
  return result;
};
