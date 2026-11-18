import { parseSpeakerNumber } from "./transcriptionFormat";

/** Number of colors in the palette (`--speaker-1 … --speaker-8`, theme.css). */
export const SPEAKER_PALETTE_SIZE = 8;

/** Maps a speaker label to its palette slot (0-based). */
export type SpeakerColors = ReadonlyMap<string, number>;

type MaybeLabel = string | null | undefined;

/** Same speaker, whatever the spelling: "speaker_0", "Speaker 0" and "0". */
const speakerKey = (raw: string): string => {
  const number = parseSpeakerNumber(raw);
  return number !== null ? `#${number}` : raw.trim().toLowerCase();
};

/**
 * Palette slot per distinct label, by first appearance in the given order
 * (stable within a meeting). More labels than colors wrap around.
 */
export const buildSpeakerColors = (
  labels: ReadonlyArray<MaybeLabel>,
): SpeakerColors => {
  const colors = new Map<string, number>();
  for (const label of labels) {
    if (!label?.trim()) continue;
    const key = speakerKey(label);
    if (!colors.has(key)) colors.set(key, colors.size % SPEAKER_PALETTE_SIZE);
  }
  return colors;
};

/** CSS class `speaker-cN` of the label, or `null` for an empty/unknown one. */
export const speakerColorClass = (
  colors: SpeakerColors,
  label: MaybeLabel,
): string | null => {
  if (!label?.trim()) return null;
  const slot = colors.get(speakerKey(label));
  return slot === undefined ? null : `speaker-c${slot + 1}`;
};
