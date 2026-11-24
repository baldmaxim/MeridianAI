import { parseInline } from '../../lib/protocolMarkdown';
import type { MdInline } from '../../lib/protocolMarkdown';

/**
 * Акценты для протокола встречи (там нет раздела «Краткое резюме», по которому включается подсветка в записи).
 * Базовый разбор — parseInline({ highlight }) из lib (суммы, %, сроки, даты, числа от двух цифр);
 * здесь добираем то, что он не покрывает: «₽», «процентов», м²/м³/т/шт/кг и т.п., однозначные числа с единицей,
 * год в дате «15.12.2026».
 */

const NUM = '(?:\\d{1,3}(?:[ \\u00a0]\\d{3})+|\\d+)(?:[.,]\\d+)?';
const UNIT =
  '(?:₽|процент(?:ов|а)?|м[²³]|м[23](?![\\d])|кв\\.?\\s*м|куб\\.?\\s*м|пог\\.?\\s*м|тонн[аыу]?|т(?!\\.\\p{L})|шт\\.?|штук[аи]?|кг)';
const UNIT_END = '(?![\\p{L}\\d_])';

/** «500 ₽», «5 т», «3 штуки», «20 процентов», «1 200 м²» — число и единица, не часть слова и не «Спикер 1». */
const NUM_UNIT_RE = new RegExp(
  `(?<![\\p{L}\\d_])(?<!(?:Спикер|Speaker)[ _])${NUM}(?:\\s*[–—-]\\s*${NUM})?\\s*${UNIT}${UNIT_END}`,
  'giu'
);

/** Единица сразу после уже выделенного числа: «500» + « ₽». */
const TAIL_UNIT_RE = new RegExp(`^\\s*${UNIT}${UNIT_END}`, 'iu');
/** Год после даты «15.12» + «.2026». */
const TAIL_YEAR_RE = /^\.\d{2,4}(?![\p{L}\d_])/u;

const DATE_DM_RE = /^\d{1,2}[.,]\d{1,2}$/;
const startsWithDigit = (s: string): boolean => /^\d/.test(s);

/** Текст → text/mark по NUM_UNIT_RE. null — если выделять нечего. */
function markUnits(text: string): MdInline[] | null {
  const out: MdInline[] = [];
  let last = 0;
  for (const m of text.matchAll(NUM_UNIT_RE)) {
    if (m.index > last) out.push({ type: 'text', text: text.slice(last, m.index) });
    out.push({ type: 'mark', text: m[0] });
    last = m.index + m[0].length;
  }
  if (out.length === 0) return null;
  if (last < text.length) out.push({ type: 'text', text: text.slice(last) });
  return out;
}

function extend(nodes: MdInline[]): MdInline[] {
  // 1. Хвост у уже выделенного числа (единица, год): расширяем mark за счёт следующих узлов.
  const merged: MdInline[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    const prev = merged[merged.length - 1];
    if (n.type === 'text' && prev?.type === 'mark' && startsWithDigit(prev.text)) {
      // «15.12» + «.» + «2026» (lib метит год отдельно)
      const next = nodes[i + 1];
      if (n.text === '.' && next?.type === 'mark' && /^\d{4}$/.test(next.text) && DATE_DM_RE.test(prev.text)) {
        prev.text += `.${next.text}`;
        i++;
        continue;
      }
      const unit = /\d$/.test(prev.text) ? n.text.match(TAIL_UNIT_RE) : null;
      const year = DATE_DM_RE.test(prev.text) ? n.text.match(TAIL_YEAR_RE) : null;
      const tail = unit ?? year;
      if (tail) {
        prev.text += tail[0];
        const rest = n.text.slice(tail[0].length);
        if (rest) merged.push({ type: 'text', text: rest });
        continue;
      }
    }
    merged.push(n.type === 'mark' ? { ...n } : n);
  }

  // 2. Число с единицей внутри обычного текста и внутри жирного.
  return merged.flatMap((n): MdInline[] => {
    if (n.type === 'text') return markUnits(n.text) ?? [n];
    if (n.type === 'strong') {
      const children = n.children ? extend(n.children) : markUnits(n.text);
      return [children && children.some((c) => c.type !== 'text') ? { type: 'strong', text: n.text, children } : n];
    }
    return [n];
  });
}

/** Инлайн-разбор с акцентами для протокола встречи. timecodes — чипы времени (как в записи). */
export function parseHighlighted(text: string, opts: { timecodes?: boolean } = {}): MdInline[] {
  return extend(parseInline(text, { highlight: true, timecodes: opts.timecodes }));
}
