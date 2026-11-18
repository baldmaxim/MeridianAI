import type { FC } from 'react';
import type { TranscriptSegmentRecord } from '../../types';
import { foreignLanguageBadge, formatDiarizedSpeaker } from '../../lib/segmentMeta';
import { getDiarizedSpeakerColor } from '../../styles/theme';
import { TranslatedText } from '../../components/common/TranslatedText';
import { formatTime, getSpeakerColorIndex } from './meetingDetailFormat';
import meta from '../../components/meeting/SegmentMeta.module.css';
import styles from './TranscriptRow.module.css';

interface ITranscriptRowProps {
  segment: TranscriptSegmentRecord;
}

export const TranscriptRow: FC<ITranscriptRowProps> = ({ segment }) => {
  const speaker = segment.speaker_label || segment.speaker_id;
  const language = foreignLanguageBadge(segment.language);
  const diarized = segment.diarized_speaker;
  return (
    <div className={styles.row}>
      <span className={styles.time}>{formatTime(segment.wall_clock)}</span>
      <span className={`${styles.speaker} ${styles[`speaker${getSpeakerColorIndex(speaker)}`]}`}>{speaker}</span>
      <span className={styles.text}>
        {language && !segment.translation && <span className={meta.langBadge} title="Язык реплики">{language}</span>}
        {diarized && (
          <span
            className={meta.diarSpeaker}
            style={{ color: getDiarizedSpeakerColor(diarized) }}
            title="Говорящий по распознаванию голоса"
          >
            {formatDiarizedSpeaker(diarized)}
          </span>
        )}
        {((language && !segment.translation) || diarized) && ' '}
        <TranslatedText text={segment.text} translation={segment.translation} language={segment.language} />
      </span>
    </div>
  );
};
