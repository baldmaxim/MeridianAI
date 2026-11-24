/**
 * Accents of a protocol text: sums, percents, terms, dates, numbers of two or
 * more digits, a number with a unit, the year of "15.12.2026". The rules are
 * the site's (meridian-web protocolMarkdown.ts + protocolHighlight.ts).
 *
 * No lookbehind here (like timecodes.ts: older system WebKit fails to load a
 * module that has one): the left border is checked in code after a match.
 */

export interface IHighlightSegment {
  text: string;
  mark: boolean;
}

type Node = { type: "text" | "mark" | "timecode"; text: string };

const TC = "\\d{1,2}:[0-5]\\d(?::[0-5]\\d)?";
/** "(03:19–04:34)" or a bare "03:19–04:34" (the left border of the bare one is checked in code). */
const TIMECODE_RE = new RegExp(
  `\\(\\s*${TC}(?:\\s*[–—,;-]\\s*${TC})*\\s*\\)|${TC}(?:\\s*[–—-]\\s*${TC})?(?![\\d:])`,
  "g",
);

const MONTH =
  "(?:январ[ьяюе]|феврал[ьяюе]|март[аеу]?|апрел[ьяюе]|ма[йяею]|июн[ьяюе]|июл[ьяюе]|август[аеу]?|сентябр[ьяюе]|октябр[ьяюе]|ноябр[ьяюе]|декабр[ьяюе])";
const NUM = "(?:\\d{1,3}(?:[ \\u00a0]\\d{3})+|\\d+)(?:[.,]\\d+)?";
const RANGE = `${NUM}(?:\\s*[–—-]\\s*${NUM})?`;
const CUR_WORD =
  "(?:руб(?:лей|ля|\\.)?|тенге|тг\\.?|долл(?:аров|ара|\\.)?|USD|EUR|евро)";
const MULT =
  "(?:тысяч|тыс|миллиардов|миллиарда|миллиард|миллионов|миллиона|миллион|млрд|млн|трлн)\\.?";
const MONEY = `(?:${MULT}(?:\\s*(?:${CUR_WORD}|[₸$€]))?|${CUR_WORD}|[₸$€])(?:\\s*/\\s*м[²23]?)?`;
const TIME_UNIT =
  "(?:месяц(?:а|ев)?|мес\\.?|дн(?:я|ей|ь|и)|недел(?:ь|и|ю|я)|лет|год(?:а|у)?|квартал(?:а|ов)?|час(?:а|ов)?)";

/** A date, a number with a unit (%, money, terms), a number of 2+ digits / with thousands, a month. */
const MARK_RE = new RegExp(
  "(?:" +
    `\\d{1,2}\\s+${MONTH}(?:\\s+\\d{4}(?:\\s*г(?:ода|\\.)?)?)?` +
    `|${RANGE}\\s*(?:%|${MONEY}|${TIME_UNIT})` +
    `|(?:\\d{1,3}(?:[ \\u00a0]\\d{3})+|\\d{2,})(?:[.,]\\d+)?(?:\\s*[–—-]\\s*${NUM})?` +
    `|\\d(?:[.,]\\d+)?\\s*[–—-]\\s*${NUM}` +
    `|${MONTH}(?:\\s*[–—-]\\s*${MONTH})?` +
    ")(?![\\p{L}\\d_])",
  "giu",
);

const UNIT =
  "(?:₽|процент(?:ов|а)?|м[²³]|м[23](?![\\d])|кв\\.?\\s*м|куб\\.?\\s*м|пог\\.?\\s*м|тонн[аыу]?|т(?!\\.\\p{L})|шт\\.?|штук[аи]?|кг)";
const UNIT_END = "(?![\\p{L}\\d_])";

/** "500 ₽", "5 т", "3 штуки", "20 процентов", "1 200 м²": a number and a unit. */
const NUM_UNIT_RE = new RegExp(
  `${NUM}(?:\\s*[–—-]\\s*${NUM})?\\s*${UNIT}${UNIT_END}`,
  "giu",
);

/** A unit right after an already marked number: "500" + " ₽". */
const TAIL_UNIT_RE = new RegExp(`^\\s*${UNIT}${UNIT_END}`, "iu");
/** A year after a date: "15.12" + ".2026". */
const TAIL_YEAR_RE = /^\.\d{2,4}(?![\p{L}\d_])/u;

const DATE_DM_RE = /^\d{1,2}[.,]\d{1,2}$/;
const startsWithDigit = (s: string): boolean => /^\d/.test(s);

const SPEAKER_BEFORE_RE = /(?:Спикер|Speaker)[ _]$/iu;
const WORD_CHAR_END_RE = /[\p{L}\d_]$/u;
const TIME_CHAR_END_RE = /[\d:]$/;

/** The match does not start inside a word and is not the number of "Спикер 1". */
const okWordStart = (text: string, index: number): boolean => {
  const before = text.slice(Math.max(0, index - 8), index);
  return !WORD_CHAR_END_RE.test(before) && !SPEAKER_BEFORE_RE.test(before);
};

/** All the matches of `re` whose start passes `accept` (a rejected start: go on from the next char). */
const matchBounded = (
  re: RegExp,
  text: string,
  accept: (match: RegExpExecArray) => boolean,
): RegExpExecArray[] => {
  const result: RegExpExecArray[] = [];
  re.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (accept(match)) {
      result.push(match);
    } else {
      re.lastIndex = match.index + 1;
    }
  }
  return result;
};

const pushMarks = (out: Node[], text: string): void => {
  let last = 0;
  for (const m of matchBounded(MARK_RE, text, (x) =>
    okWordStart(text, x.index),
  )) {
    if (m.index < last) continue;
    if (m.index > last) out.push({ type: "text", text: text.slice(last, m.index) });
    out.push({ type: "mark", text: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ type: "text", text: text.slice(last) });
};

/** text/mark/timecode; the times are cut out first so that their digits are not marked. */
const baseNodes = (text: string): Node[] => {
  const out: Node[] = [];
  let last = 0;
  const times = matchBounded(
    TIMECODE_RE,
    text,
    (x) =>
      x[0].startsWith("(") ||
      !TIME_CHAR_END_RE.test(text.slice(Math.max(0, x.index - 1), x.index)),
  );
  for (const m of times) {
    pushMarks(out, text.slice(last, m.index));
    out.push({ type: "timecode", text: m[0] });
    last = m.index + m[0].length;
  }
  pushMarks(out, text.slice(last));
  return out;
};

/** A number and a unit inside a plain text. null: nothing to mark. */
const markUnits = (text: string): Node[] | null => {
  const out: Node[] = [];
  let last = 0;
  for (const m of matchBounded(NUM_UNIT_RE, text, (x) =>
    okWordStart(text, x.index),
  )) {
    if (m.index < last) continue;
    if (m.index > last) out.push({ type: "text", text: text.slice(last, m.index) });
    out.push({ type: "mark", text: m[0] });
    last = m.index + m[0].length;
  }
  if (out.length === 0) return null;
  if (last < text.length) out.push({ type: "text", text: text.slice(last) });
  return out;
};

const extend = (nodes: Node[]): Node[] => {
  // 1. A tail of a marked number (a unit, a year): the mark takes the next nodes.
  const merged: Node[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    const prev = merged[merged.length - 1];
    if (n.type === "text" && prev?.type === "mark" && startsWithDigit(prev.text)) {
      const next = nodes[i + 1];
      if (
        n.text === "." &&
        next?.type === "mark" &&
        /^\d{4}$/.test(next.text) &&
        DATE_DM_RE.test(prev.text)
      ) {
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
        if (rest) merged.push({ type: "text", text: rest });
        continue;
      }
    }
    merged.push(n.type === "mark" ? { ...n } : n);
  }
  // 2. A number with a unit inside a plain text.
  return merged.flatMap((n): Node[] =>
    n.type === "text" ? (markUnits(n.text) ?? [n]) : [n],
  );
};

/** A text -> pieces in order; `mark` ones are the accents. A time is never an accent. */
export const highlightSegments = (text: string): IHighlightSegment[] => {
  const segments: IHighlightSegment[] = [];
  for (const node of extend(baseNodes(text))) {
    if (!node.text) continue;
    const mark = node.type === "mark";
    const prev = segments[segments.length - 1];
    if (prev && prev.mark === mark) prev.text += node.text;
    else segments.push({ text: node.text, mark });
  }
  return segments;
};
