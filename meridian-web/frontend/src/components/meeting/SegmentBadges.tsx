import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { foreignLanguageBadge, formatDiarizedSpeaker, uniqueInOrder } from '../../lib/segmentMeta';
import { getDiarizedSpeakerColor } from '../../styles/theme';
import styles from './SegmentMeta.module.css';

interface ISegmentBadgesProps {
  segmentIds: string[];
}

// Бейдж иностранного языка и метка говорящего (диаризация) у реплики или хода из нескольких реплик
export const SegmentBadges: FC<ISegmentBadgesProps> = ({ segmentIds }) => {
  const committedSegments = useMeetingStore((s) => s.committedSegments);
  const segmentSpeakers = useMeetingStore((s) => s.segmentSpeakers);

  const ids = new Set(segmentIds);
  const languages = uniqueInOrder(
    committedSegments
      .filter((seg) => ids.has(seg.segment_id))
      .map((seg) => foreignLanguageBadge(seg.language))
      .filter((code): code is string => code !== null),
  );
  const speakers = uniqueInOrder(
    segmentIds.map((id) => segmentSpeakers[id]).filter((label): label is string => !!label),
  );

  return (
    <>
      {languages.map((code) => (
        <span key={code} className={styles.langBadge} title="Язык реплики">{code}</span>
      ))}
      {speakers.map((label) => (
        <span
          key={label}
          className={styles.diarSpeaker}
          style={{ color: getDiarizedSpeakerColor(label) }}
          title="Говорящий по распознаванию голоса"
        >
          {formatDiarizedSpeaker(label)}
        </span>
      ))}
    </>
  );
};
