import type { FC, KeyboardEvent, RefObject } from 'react';
import type { TranscriptSegmentRecord } from '../../types';
import { foreignLanguageBadge, formatDiarizedSpeaker } from '../../lib/segmentMeta';
import { getDiarizedSpeakerColor } from '../../styles/theme';
import { KaraokeText } from './KaraokeText';
import { TranslatedText } from '../../components/common/TranslatedText';
import { formatTime, getSpeakerColorIndex } from './meetingDetailFormat';
import { cx } from '../../utils/cx';
import { humanSpeakerLabel } from './speakerList';
import meta from '../../components/meeting/SegmentMeta.module.css';
import styles from './TranscriptRow.module.css';

interface ITranscriptRowProps {
  segment: TranscriptSegmentRecord;
  /** Имя, заданное вручную; без него — человекочитаемая метка. */
  speakerName?: string | null;
  side?: 'self' | 'opponent' | null;
  /** Реплика, которая сейчас звучит в плеере. */
  active?: boolean;
  /** Аудио записи: у активной строки со словами звучащее слово подсвечивается. */
  audioRef?: RefObject<HTMLAudioElement | null>;
  /** Задан — строка кликабельна (перемотка записи к реплике). */
  onSeek?: () => void;
}

export const TranscriptRow: FC<ITranscriptRowProps> = ({ segment, speakerName, side, active = false, audioRef, onSeek }) => {
  const speaker = segment.speaker_label || segment.speaker_id;
  const speakerLabel = speakerName || humanSpeakerLabel(speaker);
  const language = foreignLanguageBadge(segment.language);
  const diarized = segment.diarized_speaker;
  // Выделение текста мышью не должно прыгать плеер
  const handleClick = () => {
    if (window.getSelection()?.toString()) return;
    onSeek?.();
  };
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSeek?.();
    }
  };
  const seekProps = onSeek
    ? { role: 'button', tabIndex: 0, onClick: handleClick, onKeyDown: handleKeyDown }
    : {};
  return (
    <div className={cx(styles.row, onSeek && styles.rowSeekable, active && styles.rowActive)} {...seekProps}>
      <span className={styles.time}>{formatTime(segment.wall_clock)}</span>
      <span className={styles.speakerCol}>
        <span
          className={`${styles.speaker} ${styles[`speaker${getSpeakerColorIndex(speaker)}`]}`}
          title={speakerLabel}
        >
          {speakerLabel}
        </span>
        {side && (
          <span className={`${styles.sideTag} ${side === 'self' ? styles.sideSelf : styles.sideOpp}`}>
            {side === 'self' ? 'Мы' : 'Оппонент'}
          </span>
        )}
      </span>
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
        {active && audioRef && segment.words?.length && !segment.translation ? (
          <KaraokeText text={segment.text} words={segment.words} audioRef={audioRef} />
        ) : (
          <TranslatedText text={segment.text} translation={segment.translation} language={segment.language} />
        )}
      </span>
    </div>
  );
};
