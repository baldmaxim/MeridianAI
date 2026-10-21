import type { FC } from 'react';
import type { TranscriptSegmentRecord } from '../../types';
import { formatTime, getSpeakerColorIndex } from './meetingDetailFormat';
import styles from './TranscriptRow.module.css';

interface ITranscriptRowProps {
  segment: TranscriptSegmentRecord;
}

export const TranscriptRow: FC<ITranscriptRowProps> = ({ segment }) => {
  const speaker = segment.speaker_label || segment.speaker_id;
  return (
    <div className={styles.row}>
      <span className={styles.time}>{formatTime(segment.wall_clock)}</span>
      <span className={`${styles.speaker} ${styles[`speaker${getSpeakerColorIndex(speaker)}`]}`}>{speaker}</span>
      <span className={styles.text}>{segment.text}</span>
    </div>
  );
};
