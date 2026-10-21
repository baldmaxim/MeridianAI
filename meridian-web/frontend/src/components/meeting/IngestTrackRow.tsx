import type { FC } from 'react';
import type { IngestTrackInfo } from '../../types';
import styles from './IngestPanel.module.css';
import tone from './Tone.module.css';

interface IIngestTrackRowProps {
  t: IngestTrackInfo;
}

export const IngestTrackRow: FC<IIngestTrackRowProps> = ({ t }) => {
  const roleLabel = t.role === 'primary' ? 'основной' : 'второй';
  const sideLabel = t.side_hint === 'self' ? 'мы' : t.side_hint === 'opponent' ? 'не мы' : '';
  return (
    <div className={styles.row}>
      <span className={styles.cTrack}>
        <span className={t.role === 'primary' ? tone.amber : tone.blue}>{roleLabel}</span>
        {sideLabel && <span className={styles.side}> · {sideLabel}</span>}
      </span>
      <span className={styles.c}>{t.buffered_frames}/{t.frames_count}</span>
      <span className={`${styles.c} ${t.gaps_count ? tone.red : tone.primary}`}>{t.gaps_count}</span>
      <span className={`${styles.c} ${t.duplicates_count ? tone.amber : tone.primary}`}>{t.duplicates_count}</span>
      <span className={`${styles.c} ${t.late_frames ? tone.amber : tone.primary}`}>{t.late_frames}</span>
      <span className={styles.c}>{Math.round(t.jitter_ms)}мс</span>
      <span className={styles.c}>{Math.round(t.drift_ms)}мс</span>
    </div>
  );
};
