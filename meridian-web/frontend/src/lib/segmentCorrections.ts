import type { SpeakerSegmentCorrection } from '../types';
import { toPublicSpeakerSide, type PublicSpeakerSide } from './speakerSides';

// Карта коррекций по segment_key (= TranscriptSegmentRecord.segment_id).
export type SegmentCorrectionMap = Record<string, SpeakerSegmentCorrection>;

/** segment_key для отображаемой реплики. У committed-сообщений id == segment_id. */
export function segmentKeyForMessage(msg: { id: string }): string {
  return msg.id;
}

/** Текущая ручная сторона-override этой реплики (для цикла переключения). */
export function segmentOverrideSide(
  corrections: SegmentCorrectionMap, key: string,
): PublicSpeakerSide | '' {
  return toPublicSpeakerSide(corrections[key]?.side);
}

/** Есть ли у реплики ручная коррекция (сторона или другой спикер). */
export function isSegmentCorrected(corrections: SegmentCorrectionMap, key: string): boolean {
  const c = corrections[key];
  return !!c && (!!c.side || !!c.corrected_speaker_label);
}

/** Эффективное отображаемое имя реплики:
 *  per-segment correction → глобальное имя спикера (speakerNames) → сырая метка. */
export function resolveSegmentSpeaker(
  key: string,
  originalSpeaker: string,
  corrections: SegmentCorrectionMap,
  speakerNames?: Record<string, string>,
): string {
  const corrected = corrections[key]?.corrected_speaker_label;
  if (corrected) return corrected;
  if (speakerNames && originalSpeaker && speakerNames[originalSpeaker]) {
    return speakerNames[originalSpeaker];
  }
  return originalSpeaker || '';
}

/** Эффективная сторона реплики (то же правило приоритета, что и на backend). */
export function resolveSegmentSide(
  key: string,
  originalSpeaker: string,
  corrections: SegmentCorrectionMap,
  speakerRoles: Record<string, string>,
): PublicSpeakerSide | '' {
  const c = corrections[key];
  if (c?.side) {
    const s = toPublicSpeakerSide(c.side);
    if (s) return s;
  }
  if (c?.corrected_speaker_label) {
    const s = toPublicSpeakerSide(speakerRoles[c.corrected_speaker_label]);
    if (s) return s;
  }
  return toPublicSpeakerSide(speakerRoles[originalSpeaker]);
}
