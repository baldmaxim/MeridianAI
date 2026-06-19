import { theme } from '../../styles/theme';
import { useObserverMic } from '../../hooks/useObserverMic';
import { SyncBadge } from './SyncBadge';

interface ObserverPanelProps {
  meetingId: number | null;
}

// Этап 9: режим «наблюдатель» для второго телефона. Устройство НЕ записывает речь в текст —
// только измеряет громкость локально и подсказывает, к какой стороне относится реплика.
export function ObserverPanel({ meetingId }: ObserverPanelProps) {
  const { active, side, level, error, sync, start, stop, setSideHint } = useObserverMic(meetingId);
  const pct = Math.min(100, Math.round(level * 400));

  return (
    <div style={styles.panel}>
      <div style={styles.note}>
        Положите этот телефон рядом с одной из сторон. Он не записывает речь в текст — только громкость,
        чтобы подсказать, чья это реплика. Звук в STT отправляет основное устройство.
      </div>

      <div style={styles.sideRow}>
        <span style={styles.label}>Рядом с:</span>
        <button
          type="button"
          style={side === 'self' ? styles.sideOnSelf : styles.sideOff}
          onClick={() => setSideHint('self')}
        >Нами</button>
        <button
          type="button"
          style={side === 'opponent' ? styles.sideOnOpp : styles.sideOff}
          onClick={() => setSideHint('opponent')}
        >Другой стороной</button>
      </div>

      <div style={styles.meterTrack}>
        <div style={{ ...styles.meterFill, width: `${pct}%` }} />
      </div>

      <div style={styles.controls}>
        {active ? (
          <button type="button" style={styles.stopBtn} onClick={stop}>Остановить наблюдение</button>
        ) : (
          <button type="button" style={styles.startBtn} onClick={() => void start()} disabled={meetingId == null}>
            Включить наблюдение
          </button>
        )}
        <span style={styles.status}>{active ? 'идёт измерение уровня…' : 'выключено'}</span>
        {active && <SyncBadge sync={sync} />}
      </div>

      {meetingId == null && <div style={styles.hint}>Сначала откройте встречу.</div>}
      {error && <div style={styles.error}>{error}</div>}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  panel: { display: 'flex', flexDirection: 'column', gap: 10 },
  note: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, lineHeight: 1.5 },
  sideRow: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const },
  label: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, letterSpacing: '0.06em' },
  sideOff: {
    padding: '8px 14px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 8, color: theme.text.secondary, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.body,
  },
  sideOnSelf: {
    padding: '8px 14px', background: 'rgba(46,229,157,0.12)', border: `1px solid ${theme.accent.green}`,
    borderRadius: 8, color: theme.accent.green, cursor: 'pointer', fontSize: 12, fontWeight: 600, fontFamily: theme.font.body,
  },
  sideOnOpp: {
    padding: '8px 14px', background: 'rgba(255,75,110,0.12)', border: `1px solid ${theme.accent.red}`,
    borderRadius: 8, color: theme.accent.red, cursor: 'pointer', fontSize: 12, fontWeight: 600, fontFamily: theme.font.body,
  },
  meterTrack: { height: 8, borderRadius: 4, background: theme.bg.input, overflow: 'hidden' },
  meterFill: { height: '100%', background: theme.accent.amber, borderRadius: 4, transition: 'width 0.1s linear' },
  controls: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' as const },
  startBtn: {
    padding: '10px 18px', background: theme.accent.amber, border: 'none', borderRadius: 8,
    color: '#080A0F', cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: theme.font.body,
  },
  stopBtn: {
    padding: '10px 18px', background: 'transparent', border: `1px solid ${theme.accent.red}`, borderRadius: 8,
    color: theme.accent.red, cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: theme.font.body,
  },
  status: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  hint: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  error: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.red },
};
