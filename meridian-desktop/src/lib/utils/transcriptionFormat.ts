import type { TranscriptSegment } from "@/bindings";

/** "mm:ss", or "h:mm:ss" from an hour on. */
export const formatTimestamp = (seconds: number): string => {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${ss}`
    : `${String(m).padStart(2, "0")}:${ss}`;
};

/** "12,3 МБ" / "850 КБ" / "40 Б" in the given locale. */
export const formatFileSize = (
  bytes: number,
  units: { b: string; kb: string; mb: string; gb: string },
  locale: string,
): string => {
  const format = (value: number, digits: number) =>
    new Intl.NumberFormat(locale, {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits,
    }).format(value);
  if (bytes >= 1024 ** 3) return `${format(bytes / 1024 ** 3, 1)} ${units.gb}`;
  if (bytes >= 1024 ** 2) return `${format(bytes / 1024 ** 2, 1)} ${units.mb}`;
  if (bytes >= 1024) return `${format(bytes / 1024, 0)} ${units.kb}`;
  return `${bytes} ${units.b}`;
};

/**
 * "Спикер N" for a server label such as "speaker_0" or "0" (numbered from 1);
 * any other label is shown as it came.
 */
export const speakerLabel = (raw: string, prefix: string): string => {
  const match = /^(?:speaker[_ -]?)?(\d+)$/i.exec(raw.trim());
  if (match) return `${prefix} ${Number(match[1]) + 1}`;
  return raw.trim() || prefix;
};

/** One line per phrase: "[mm:ss] Спикер N: текст". */
export const transcriptToText = (
  segments: TranscriptSegment[],
  fallbackText: string,
  speakerPrefix: string,
): string => {
  if (segments.length === 0) return fallbackText;
  return segments
    .map(
      (s) =>
        `[${formatTimestamp(s.start)}] ${speakerLabel(s.speaker, speakerPrefix)}: ${s.text}`,
    )
    .join("\n");
};
