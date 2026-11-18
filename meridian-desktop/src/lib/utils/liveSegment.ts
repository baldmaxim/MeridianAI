/** Helpers for phrases recognized live on the server. */

const RUSSIAN_CODES = new Set(["ru", "rus"]);
const DIARIZED_RE = /^s(\d+)_speaker_(\d+)$/i;

/** Code to show as a badge: a known language other than Russian ("tr" → "TR"). */
export const foreignLanguageBadge = (
  code: string | null | undefined,
): string | null => {
  const base = (code ?? "").trim().toLowerCase().split("-")[0];
  if (!base || RUSSIAN_CODES.has(base)) return null;
  return base.toUpperCase();
};

/**
 * "s1_speaker_0" → "Спикер 1". The numbering starts over in a later session
 * of the server's recognition, so a session after the first is named too.
 * Any other label is returned as it came.
 */
export const formatDiarizedSpeaker = (
  label: string,
  prefix: string,
  session: (n: number) => string,
): string => {
  const match = DIARIZED_RE.exec(label.trim());
  if (!match) return label;
  const name = `${prefix} ${Number(match[2]) + 1}`;
  const n = Number(match[1]);
  return n > 1 ? `${name} (${session(n)})` : name;
};
