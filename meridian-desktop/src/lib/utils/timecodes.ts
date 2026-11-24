/** A piece of a text: plain text (`seconds` is `null`) or a time such as "12:34". */
export interface ITimecodePart {
  text: string;
  seconds: number | null;
}

// "mm:ss" or "h:mm:ss" / "hh:mm:ss"; the borders are checked in code (no
// lookbehind: older system WebKit fails to load a module that has one).
const TIMECODE_RE = /\d{1,2}:[0-5]\d(?::[0-5]\d)?/g;

const isTimeChar = (char: string | undefined): boolean =>
  char !== undefined && /[\d:]/.test(char);

/** "03:19" -> 199, "1:02:03" -> 3723; `null` when it is not a time. */
export const timecodeToSeconds = (timecode: string): number | null => {
  const parts = timecode.trim().split(":").map(Number);
  if (parts.length < 2 || parts.length > 3) return null;
  if (parts.some((n) => !Number.isInteger(n) || n < 0)) return null;
  if (parts[parts.length - 1] >= 60) return null;
  if (parts.length === 3) {
    if (parts[1] >= 60) return null;
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  return parts[0] * 60 + parts[1];
};

/** A text -> plain pieces and times in order ("[12:34]" keeps its brackets as text). */
export const splitTimecodes = (text: string): ITimecodePart[] => {
  const parts: ITimecodePart[] = [];
  let last = 0;
  for (const match of text.matchAll(TIMECODE_RE)) {
    const index = match.index ?? 0;
    const end = index + match[0].length;
    if (isTimeChar(text[index - 1]) || isTimeChar(text[end])) continue;
    const seconds = timecodeToSeconds(match[0]);
    if (seconds === null) continue;
    if (index > last) {
      parts.push({ text: text.slice(last, index), seconds: null });
    }
    parts.push({ text: match[0], seconds });
    last = end;
  }
  if (last < text.length) {
    parts.push({ text: text.slice(last), seconds: null });
  }
  return parts;
};
