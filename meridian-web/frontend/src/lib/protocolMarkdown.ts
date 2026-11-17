/** Лёгкий разбор Markdown протокола: чистые функции без React (общие для сайта и HTML-экспорта). */

export type MdInline =
  | { type: 'text'; text: string }
  | { type: 'strong'; text: string }
  | { type: 'code'; text: string };

export type MdBlock =
  | { type: 'heading'; level: number; text: string }
  | { type: 'ul'; items: string[] }
  | { type: 'ol'; start: number; items: string[] }
  | { type: 'table'; header: string[]; rows: string[][] }
  | { type: 'p'; text: string };

/** Инлайн-разметка: **жирный** и `код`. */
export function parseInline(text: string): MdInline[] {
  const nodes: MdInline[] = [];
  const re = /\*\*(.+?)\*\*|`([^`]+?)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push({ type: 'text', text: text.slice(last, m.index) });
    if (m[1] != null) nodes.push({ type: 'strong', text: m[1] });
    else nodes.push({ type: 'code', text: m[2] });
    last = re.lastIndex;
  }
  if (last < text.length) nodes.push({ type: 'text', text: text.slice(last) });
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
      blocks.push({ type: 'ul', items });
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
      blocks.push({ type: 'ol', start, items });
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
    blocks.push({ type: 'p', text: para.join(' ') });
  }

  return blocks;
}
