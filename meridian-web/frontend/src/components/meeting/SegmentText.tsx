import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { foreignLanguageBadge, uniqueInOrder } from '../../lib/segmentMeta';
import { TranslatedText } from '../common/TranslatedText';

interface ISegmentTextProps {
  segmentIds: string[];
  /** Исходный текст реплики или хода. */
  text: string;
  className?: string;
}

// Текст реплики/хода: пока перевода нет — оригинал; пришёл перевод — он главный, оригинал под ним.
// Ход из нескольких реплик собирается по сегментам: переведённые заменяются переводом, русские остаются как есть.
export const SegmentText: FC<ISegmentTextProps> = ({ segmentIds, text, className }) => {
  const translations = useMeetingStore((s) => s.segmentTranslations);
  const committedSegments = useMeetingStore((s) => s.committedSegments);

  const translatedIds = segmentIds.filter((id) => !!translations[id]);
  if (translatedIds.length === 0) return <span className={className}>{text}</span>;

  const byId = new Map(committedSegments.map((seg) => [seg.segment_id, seg]));
  const main = segmentIds
    .map((id) => translations[id] || byId.get(id)?.text)
    .filter(Boolean)
    .join(' ');
  const original = translatedIds.map((id) => byId.get(id)?.text).filter(Boolean).join(' ') || text;
  const languages = uniqueInOrder(
    translatedIds
      .map((id) => foreignLanguageBadge(byId.get(id)?.language))
      .filter((code): code is string => code !== null),
  );

  return <TranslatedText text={original} translation={main} language={languages[0]} className={className} />;
};
