import type { TranscriptSegmentRecord } from '../../types';
import { formatDiarizedSpeaker } from '../../lib/segmentMeta';

export interface IMeetingSpeaker {
  /** Сырая метка из транскрипта — ключ ролей на сервере. */
  label: string;
  count: number;
  /** Пример реплики, чтобы понять, кто это. */
  sample: string;
}

const DIARIZED_RE = /^s\d+_speaker_\d+$/i;
const SPEAKER_NUM_RE = /^(?:speaker[_\s-]*)+(\d+)$/i;
const SAMPLE_MIN = 60;
const SAMPLE_MAX = 200;
const SAMPLE_CUT = 140;

/** «Speaker_speaker_0» → «Спикер 1», «s2_speaker_1» → «Спикер 2 (сессия 2)»; прочие метки (имена) — как есть. */
export const humanSpeakerLabel = (label: string): string => {
  const raw = label.trim();
  if (DIARIZED_RE.test(raw)) return formatDiarizedSpeaker(raw);
  const m = SPEAKER_NUM_RE.exec(raw);
  return m ? `Спикер ${Number(m[1]) + 1}` : label;
};

export const segmentSpeakerKey = (seg: TranscriptSegmentRecord): string => seg.speaker_label || seg.speaker_id;

const cut = (text: string): string => (text.length > SAMPLE_CUT ? `${text.slice(0, SAMPLE_CUT).trimEnd()}…` : text);

/** Уникальные спикеры встречи в порядке первого появления: число реплик и пример (60–200 символов, иначе первая непустая). */
export const buildSpeakerList = (segments: TranscriptSegmentRecord[]): IMeetingSpeaker[] => {
  const map = new Map<string, { count: number; good: string; first: string }>();
  for (const seg of segments) {
    const label = segmentSpeakerKey(seg);
    if (!label) continue;
    const text = (seg.text ?? '').trim();
    const item = map.get(label) ?? { count: 0, good: '', first: '' };
    item.count += 1;
    if (text) {
      if (!item.first) item.first = text;
      if (!item.good && text.length >= SAMPLE_MIN && text.length <= SAMPLE_MAX) item.good = text;
    }
    map.set(label, item);
  }
  return Array.from(map, ([label, v]) => ({ label, count: v.count, sample: cut(v.good || v.first) }));
};
