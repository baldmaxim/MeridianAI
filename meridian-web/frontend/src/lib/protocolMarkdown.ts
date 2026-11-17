/** Лёгкий разбор Markdown протокола: чистые функции без React (общие для сайта и HTML-экспорта). */

export type MdInline =
  | { type: 'text'; text: string }
  /** children — только при highlight/timecodes и если внутри жирного есть mark/timecode. */
  | { type: 'strong'; text: string; children?: MdInline[] }
  | { type: 'code'; text: string }
  /** Ключевое число/срок/дата (только при highlight). */
  | { type: 'mark'; text: string }
  /**
   * В «Кратком резюме» (highlight) — «(03:19–04:34)» целиком, со скобками;
   * при timecodes вне резюме — одно время «03:19» (диапазон = два узла).
   */
  | { type: 'timecode'; text: string };

/** summary: true — блок внутри раздела «Краткое резюме». */
export type MdBlock =
  | { type: 'heading'; level: number; text: string }
  | { type: 'ul'; items: string[]; summary?: boolean }
  | { type: 'ol'; start: number; items: string[]; summary?: boolean }
  | { type: 'table'; header: string[]; rows: string[][] }
  | { type: 'p'; text: string; summary?: boolean };

// ── Выделение главного в «Кратком резюме» ──
const TC = '\\d{1,2}:[0-5]\\d(?::[0-5]\\d)?';
/** «(03:19–04:34)», «(03:19, 05:10)» или голый «03:19–04:34». */
const TIMECODE_RE = new RegExp(
  `\\(\\s*${TC}(?:\\s*[–—,;-]\\s*${TC})*\\s*\\)|(?<![\\d:])${TC}(?:\\s*[–—-]\\s*${TC})?(?![\\d:])`,
  'g'
);

/** Одно время «03:19» / «1:02:03» (отдельно, без захвата скобок и диапазонов). */
const SINGLE_TC_RE = new RegExp(`(?<![\\d:])${TC}(?![\\d:])`, 'g');

/** «03:19» → 199, «1:02:03» → 3723; null, если это не время (секунды ≥ 60). */
export function timecodeToSeconds(tc: string): number | null {
  const parts = tc.split(':').map(Number);
  if (parts.some((n) => Number.isNaN(n)) || parts[parts.length - 1] >= 60) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return parts[0] * 60 + parts[1];
}

/** Текст → части: время (seconds) и обычный текст между ними (seconds = null). */
export function splitTimecodes(text: string): Array<{ text: string; seconds: number | null }> {
  const out: Array<{ text: string; seconds: number | null }> = [];
  let last = 0;
  for (const m of text.matchAll(SINGLE_TC_RE)) {
    const sec = timecodeToSeconds(m[0]);
    if (sec == null) continue;
    if (m.index > last) out.push({ text: text.slice(last, m.index), seconds: null });
    out.push({ text: m[0], seconds: sec });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), seconds: null });
  return out;
}

const MONTH =
  '(?:январ[ьяюе]|феврал[ьяюе]|март[аеу]?|апрел[ьяюе]|ма[йяею]|июн[ьяюе]|июл[ьяюе]|август[аеу]?|сентябр[ьяюе]|октябр[ьяюе]|ноябр[ьяюе]|декабр[ьяюе])';
const NUM = '(?:\\d{1,3}(?:[ \\u00a0]\\d{3})+|\\d+)(?:[.,]\\d+)?';
const RANGE = `${NUM}(?:\\s*[–—-]\\s*${NUM})?`;
const CUR_WORD = '(?:руб(?:лей|ля|\\.)?|тенге|тг\\.?|долл(?:аров|ара|\\.)?|USD|EUR|евро)';
const MULT = '(?:тысяч|тыс|миллиардов|миллиарда|миллиард|миллионов|миллиона|миллион|млрд|млн|трлн)\\.?';
const MONEY = `(?:${MULT}(?:\\s*(?:${CUR_WORD}|[₸$€]))?|${CUR_WORD}|[₸$€])(?:\\s*/\\s*м[²23]?)?`;
const TIME_UNIT =
  '(?:месяц(?:а|ев)?|мес\\.?|дн(?:я|ей|ь|и)|недел(?:ь|и|ю|я)|лет|год(?:а|у)?|квартал(?:а|ов)?|час(?:а|ов)?)';

/** Дата, число с единицей (%, деньги, сроки), число ≥ 2 цифр / с разделителями тысяч, месяц. */
const MARK_RE = new RegExp(
  '(?<![\\p{L}\\d_])(?<!(?:Спикер|Speaker)[ _])(?:' +
    `\\d{1,2}\\s+${MONTH}(?:\\s+\\d{4}(?:\\s*г(?:ода|\\.)?)?)?` +
    `|${RANGE}\\s*(?:%|${MONEY}|${TIME_UNIT})` +
    `|(?:\\d{1,3}(?:[ \\u00a0]\\d{3})+|\\d{2,})(?:[.,]\\d+)?(?:\\s*[–—-]\\s*${NUM})?` +
    `|\\d(?:[.,]\\d+)?\\s*[–—-]\\s*${NUM}` +
    `|${MONTH}(?:\\s*[–—-]\\s*${MONTH})?` +
    ')(?![\\p{L}\\d_])',
  'giu'
);

function pushMarks(out: MdInline[], text: string): void {
  let last = 0;
  for (const m of text.matchAll(MARK_RE)) {
    if (m.index > last) out.push({ type: 'text', text: text.slice(last, m.index) });
    out.push({ type: 'mark', text: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ type: 'text', text: text.slice(last) });
}

/** Текст → text/mark/timecode. Таймкоды вырезаются первыми, чтобы их цифры не стали mark. */
function highlightText(text: string): MdInline[] {
  const out: MdInline[] = [];
  let last = 0;
  for (const m of text.matchAll(TIMECODE_RE)) {
    pushMarks(out, text.slice(last, m.index));
    out.push({ type: 'timecode', text: m[0] });
    last = m.index + m[0].length;
  }
  pushMarks(out, text.slice(last));
  return out;
}

/** Текст → text/timecode (по одному узлу на каждое время), без mark. */
function timecodeText(text: string): MdInline[] {
  return splitTimecodes(text).map((p) =>
    p.seconds == null ? { type: 'text', text: p.text } : { type: 'timecode', text: p.text }
  );
}

/**
 * Инлайн-разметка: **жирный** и `код`.
 * highlight (раздел «Краткое резюме») — дополнительно узлы mark и timecode (чип со скобками).
 * timecodes (вне резюме) — только узлы timecode, по одному на каждое время; mark нет.
 * При обоих флагах действует highlight.
 */
export function parseInline(text: string, opts: { highlight?: boolean; timecodes?: boolean } = {}): MdInline[] {
  const { highlight = false, timecodes = false } = opts;
  const nodes: MdInline[] = [];
  const split = (t: string): MdInline[] | null => (highlight ? highlightText(t) : timecodes ? timecodeText(t) : null);
  const pushText = (t: string) => {
    const parts = split(t);
    if (parts) nodes.push(...parts);
    else nodes.push({ type: 'text', text: t });
  };
  const re = /\*\*(.+?)\*\*|`([^`]+?)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) pushText(text.slice(last, m.index));
    if (m[1] != null) {
      const children = split(m[1]) ?? [];
      nodes.push(children.some((c) => c.type !== 'text') ? { type: 'strong', text: m[1], children } : { type: 'strong', text: m[1] });
    } else nodes.push({ type: 'code', text: m[2] });
    last = re.lastIndex;
  }
  if (last < text.length) pushText(text.slice(last));
  return nodes;
}

function splitRow(line: string): string[] {
  return line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
}

const NUM_ITEM = /^\s*\d+[.)]\s+/;

/** «1. … 2. … 3. …» одной строкой → отдельные строки, если номера идут подряд. */
export function splitInlineNumbered(line: string): string[] {
  const m = line.match(/^\s*(\d+)[.)]\s+/);
  if (!m) return [line];
  const parts = line.split(/(?<=[.;:!?)»])\s+(?=\d{1,2}[.)]\s+\S)/);
  if (parts.length < 2) return [line];
  const start = Number(m[1]);
  const sequential = parts.every((p, idx) => Number(p.match(/^\s*(\d+)/)?.[1]) === start + idx);
  return sequential ? parts : [line];
}

/** Markdown протокола → плоский список блоков: заголовки, списки, таблицы, абзацы. */
export function parseMarkdown(md: string): MdBlock[] {
  const lines = md.replace(/\r\n/g, '\n').split('\n').flatMap(splitInlineNumbered);
  const blocks: MdBlock[] = [];
  let i = 0;
  // «Краткое резюме»: действует до следующего заголовка
  let inSummary = false;
  const sum = (): { summary?: true } => (inSummary ? { summary: true } : {});

  while (i < lines.length) {
    const line = lines[i];

    // Таблица: строка "| … |" + строка-разделитель "|---|---|"
    if (line.trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push({ type: 'table', header, rows });
      continue;
    }

    // Заголовок
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      blocks.push({ type: 'heading', level: h[1].length, text: h[2] });
      inSummary = /краткое резюме/i.test(h[2]);
      i++;
      continue;
    }

    // Маркированный список
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ''));
        i++;
      }
      blocks.push({ type: 'ul', items, ...sum() });
      continue;
    }

    // Нумерованный список
    if (NUM_ITEM.test(line)) {
      const start = Number(line.match(/\d+/)?.[0] ?? 1);
      const items: string[] = [];
      while (i < lines.length && NUM_ITEM.test(lines[i])) {
        items.push(lines[i].replace(NUM_ITEM, ''));
        i++;
      }
      blocks.push({ type: 'ol', start, items, ...sum() });
      continue;
    }

    // Пустая строка
    if (!line.trim()) { i++; continue; }

    // Абзац
    const para: string[] = [];
    while (
      i < lines.length && lines[i].trim() &&
      !/^(#{1,4})\s/.test(lines[i]) && !/^\s*[-*]\s/.test(lines[i]) && !NUM_ITEM.test(lines[i]) && !lines[i].trim().startsWith('|')
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push({ type: 'p', text: para.join(' '), ...sum() });
  }

  return blocks;
}
