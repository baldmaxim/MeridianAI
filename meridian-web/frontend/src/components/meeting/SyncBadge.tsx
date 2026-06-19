import { theme } from '../../styles/theme';
import type { DeviceSyncState, ClockSyncQuality } from '../../types';

// Этап 9.1: индикатор качества синхронизации часов устройства с backend.
// Точка-цвет по quality + RTT мс; tooltip — offset и время последней синхронизации.

const QUALITY_COLOR: Record<ClockSyncQuality, string> = {
  excellent: theme.accent.green,
  good: theme.accent.green,
  fair: theme.accent.amber,
  poor: theme.accent.red,
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
      <span style={styles.wrap} title="Часы устройства ещё не синхронизированы">
        <span style={dot(theme.text.muted)} />
        {!compact && <span style={styles.text}>sync…</span>}
      </span>
    );
  }
  const color = QUALITY_COLOR[sync.quality];
  const tip =
    `Синхронизация часов: ${QUALITY_LABEL[sync.quality]}\n` +
    `RTT ≈ ${Math.round(sync.rttMs)} мс · offset ≈ ${Math.round(sync.offsetMs)} мс\n` +
    `выборок: ${sync.samples}`;
  return (
    <span style={styles.wrap} title={tip}>
      <span style={dot(color)} />
      <span style={{ ...styles.text, color }}>
        {compact ? `${Math.round(sync.rttMs)}мс` : `sync ${Math.round(sync.rttMs)} мс`}
      </span>
    </span>
  );
}

const dot = (color: string): React.CSSProperties => ({
  width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0,
});

const styles: Record<string, React.CSSProperties> = {
  wrap: { display: 'inline-flex', alignItems: 'center', gap: 5 },
  text: {
    fontSize: 10, fontFamily: theme.font.mono, letterSpacing: '0.06em',
    color: theme.text.muted,
  },
};
