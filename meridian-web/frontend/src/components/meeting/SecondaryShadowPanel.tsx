import { theme } from '../../styles/theme';
import { useSecondaryShadow } from '../../hooks/useSecondaryShadow';
import { SyncBadge } from './SyncBadge';

interface Props {
  meetingId: number | null;
}

// Этап 9.2: режим «второй аудиоканал (shadow)» для дополнительного устройства.
// Пишет PCM-чанки на backend для будущего multi-channel. Пока БЕЗ STT: звук в текст
// по-прежнему отправляет основное устройство, а этот канал только буферизуется.
export function SecondaryShadowPanel({ meetingId }: Props) {
  const { active, side, level, error, ready, sync, diag, start, stop, setSideHint } =
    useSecondaryShadow(meetingId);
  const pct = Math.min(100, Math.round(level * 400));

  const statusText = !active
    ? 'выключено'
    : diag
      ? STATUS_LABEL[diag.status] ?? diag.status
      : ready ? 'канал готов…' : 'подключение…';

  return (
    <div style={styles.panel}>
      <div style={styles.note}>
        Это устройство пишет ВТОРОЙ аудиоканал встречи для будущего разделения по говорящим.
        Пока канал только записывается в shadow-режиме — речь в текст он не превращает
        (это делает основное устройство).
      </div>

      <div style={styles.sideRow}>
        <span style={styles.label}>Рядом с:</span>
        <button type="button" style={side === 'self' ? styles.sideOnSelf : styles.sideOff}
          onClick={() => setSideHint('self')}>Нами</button>
        <button type="button" style={side === 'opponent' ? styles.sideOnOpp : styles.sideOff}
          onClick={() => setSideHint('opponent')}>Другой стороной</button>
      </div>

      <div style={styles.meterTrack}>
        <div style={{ ...styles.meterFill, width: `${pct}%` }} />
      </div>

      {active && diag && (
        <div style={styles.diagGrid}>
          <Metric label="чанков" value={String(diag.chunks_count)} />
          <Metric label="буфер" value={`${(diag.estimated_buffer_ms / 1000).toFixed(1)} с`} />
          <Metric label="пропуски" value={String(diag.gaps_count)}
            warn={diag.gaps_count > 0} />
          <Metric label="отброшено" value={String(diag.dropped_chunks)}
            warn={diag.dropped_chunks > 0} />
          <Metric label="drift" value={`${Math.round(diag.drift_ms)} мс`} />
          <Metric label="лаг пакета"
            value={diag.last_packet_age_ms != null ? `${diag.last_packet_age_ms} мс` : '—'}
            warn={(diag.last_packet_age_ms ?? 0) > 1500} />
          <Metric label="частота"
            value={diag.sample_rate ? `${Math.round(diag.sample_rate / 1000)}к` : '—'} />
          <Metric label="кодек" value={diag.codec ?? '—'} />
        </div>
      )}

      <div style={styles.controls}>
        {active ? (
          <button type="button" style={styles.stopBtn} onClick={stop}>Остановить второй канал</button>
        ) : (
          <button type="button" style={styles.startBtn} onClick={() => void start()} disabled={meetingId == null}>
            Включить второй канал
          </button>
        )}
        <span style={styles.status}>{statusText}</span>
        {active && <SyncBadge sync={sync} />}
      </div>

      {meetingId == null && <div style={styles.hint}>Сначала откройте встречу.</div>}
      {error && <div style={styles.error}>{error}</div>}
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  idle: 'ожидание',
  recording: 'идёт запись канала…',
  stale: 'нет пакетов (проверьте связь)',
  error: 'ошибка канала',
};

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div style={styles.metric}>
      <span style={styles.metricLabel}>{label}</span>
      <span style={{ ...styles.metricValue, color: warn ? theme.accent.red : theme.text.primary }}>{value}</span>
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
  meterFill: { height: '100%', background: theme.accent.blue, borderRadius: 4, transition: 'width 0.1s linear' },
  diagGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8,
    padding: '8px 10px', background: theme.bg.input, borderRadius: 8,
  },
  metric: { display: 'flex', flexDirection: 'column', gap: 2 },
  metricLabel: { fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted, letterSpacing: '0.04em' },
  metricValue: { fontFamily: theme.font.mono, fontSize: 12, fontWeight: 600 },
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
