import { useEffect, useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { PopNumber } from '../common/PopNumber';
import styles from './MeetingStatsInline.module.css';
import tone from './Tone.module.css';

const ELAPSED_TICK_MS = 10000;

/** Метрики встречи одной строкой (для шапки на десктопе): позиция, принято, возражения, время. */
export const MeetingStatsInline: FC = () => {
  const stats = useMeetingStore((s) => s.meetingStats);
  const [now, setNow] = useState(() => Date.now());

  const startTime = stats.meetingStartTime;
  const elapsed = startTime ? `${Math.max(0, Math.floor((now - startTime) / 60000))}м` : '0м';

  useEffect(() => {
    if (!startTime) return;
    const id = setInterval(() => setNow(Date.now()), ELAPSED_TICK_MS);
    return () => clearInterval(id);
  }, [startTime]);

  return (
    <div className={styles.row} aria-label="Динамика встречи">
      <span className={styles.item}>
        <span className={styles.label}>Позиция</span>
        <span className={`${styles.value} ${stats.positionStrength >= 60 ? tone.green : tone.amber}`}>
          <PopNumber value={`${stats.positionStrength}%`} />
        </span>
      </span>
      <span className={styles.item}>
        <span className={styles.label}>Принято</span>
        <span className={`${styles.value} ${tone.green}`}><PopNumber value={stats.suggestionsUsed} /></span>
      </span>
      <span className={styles.item}>
        <span className={styles.label}>Возраж.</span>
        <span className={`${styles.value} ${stats.activeObjections > 0 ? tone.red : tone.primary}`}>
          <PopNumber value={stats.activeObjections} />
        </span>
      </span>
      <span className={styles.item}>
        <span className={styles.label}>Время</span>
        <span className={styles.value}><PopNumber value={elapsed} /></span>
      </span>
    </div>
  );
};
