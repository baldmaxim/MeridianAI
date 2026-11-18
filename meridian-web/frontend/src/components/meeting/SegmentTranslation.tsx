import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import styles from './SegmentMeta.module.css';

interface ISegmentTranslationProps {
  segmentIds: string[];
}

// Перевод иноязычных реплик на русский — под текстом, приглушённым цветом
export const SegmentTranslation: FC<ISegmentTranslationProps> = ({ segmentIds }) => {
  const translations = useMeetingStore((s) => s.segmentTranslations);
  const text = segmentIds.map((id) => translations[id]).filter(Boolean).join(' ');
  if (!text) return null;
  return <span className={styles.translation} title="Перевод на русский">{text}</span>;
};
