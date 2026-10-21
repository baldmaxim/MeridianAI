/** Склейка классов: пропускает пустые значения (false/null/undefined/''). */
export const cx = (...parts: Array<string | false | null | undefined>): string =>
  parts.filter(Boolean).join(' ');
