import type { DeviceSyncState, ClockSyncQuality } from '../../types';
import styles from './SyncBadge.module.css';

// Этап 9.1: индикатор качества синхронизации часов устройства с backend.
// Точка-цвет по quality + RTT мс; tooltip — offset и время последней синхронизации.

const QUALITY_TONE: Record<ClockSyncQuality, { text: string; dot: string }> = {
  excellent: { text: styles.textGreen, dot: styles.dotGreen },
  good: { text: styles.textGreen, dot: styles.dotGreen },
  fair: { text: styles.textAmber, dot: styles.dotAmber },
  poor: { text: styles.textRed, dot: styles.dotRed },
};

const QUALITY_LABEL: Record<ClockSyncQuality, string> = {
  excellent: 'отличная',
  good: 'хорошая',
  fair: 'средняя',
  poor: 'плохая',
};

interface Props {
  sync: DeviceSyncState | null;
  compact?: boolean;  // true — только точка + RTT (для нижней панели)
}

export function SyncBadge({ sync, compact = false }: Props) {
  if (!sync) {
    return (
      <span className={styles.wrap} title="Часы устройства ещё не синхронизированы">
        <span className={`${styles.dot} ${styles.dotMuted}`} />
        {!compact && <span className={styles.text}>sync…</span>}
      </span>
    );
  }
  const qTone = QUALITY_TONE[sync.quality];
  const tip =
    `Синхронизация часов: ${QUALITY_LABEL[sync.quality]}\n` +
    `RTT ≈ ${Math.round(sync.rttMs)} мс · offset ≈ ${Math.round(sync.offsetMs)} мс\n` +
    `выборок: ${sync.samples}`;
  return (
    <span className={styles.wrap} title={tip}>
      <span className={`${styles.dot} ${qTone.dot}`} />
      <span className={`${styles.text} ${qTone.text}`}>
        {compact ? `${Math.round(sync.rttMs)}мс` : `sync ${Math.round(sync.rttMs)} мс`}
      </span>
    </span>
  );
}
