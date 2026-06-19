import { useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import type { IngestTrackInfo } from '../../types';
import { MultiChannelExportModal } from './MultiChannelExportModal';

// Этап 9.3: монитор multi-source ingest. Показывает, что backend свёл аудиоисточники
// к ОДНОЙ server timeline: общий диапазон canonical-фреймов (один и тот же интервал
// для всех треков) + per-track метрики качества (gaps/dup/late/jitter/drift).
// Пока без mux/STT для secondary — только выравнивание.
export function IngestPanel() {
  const al = useMeetingStore((s) => s.ingestAlignment);
  const meetingId = useMeetingStore((s) => s.currentMeetingId);
  const [exportOpen, setExportOpen] = useState(false);

  if (!al || al.tracks.length === 0) {
    return <div style={styles.note}>Второй источник ещё не подключён. Здесь появится выравнивание
      каналов по единой временной шкале, когда пишет основной и/или второй канал.</div>;
  }

  const canExport = meetingId != null && al.tracks.some((t) => t.buffered_frames > 0);

  const aligned = al.common_lo != null && al.common_hi != null
    ? `${al.common_hi - al.common_lo + 1} фреймов (#${al.common_lo}–${al.common_hi})`
    : '—';

  return (
    <div style={styles.panel}>
      <div style={styles.note}>
        Backend сводит источники к единой шкале (кадр = {al.frame_ms} мс). Совпадающий
        диапазон фреймов = общий временной интервал каналов.
      </div>
      <div style={styles.common}>
        <span style={styles.commonLabel}>общий выровненный интервал</span>
        <span style={styles.commonValue}>{aligned}</span>
      </div>
      <div style={styles.table}>
        <div style={{ ...styles.row, ...styles.head }}>
          <span style={styles.cTrack}>канал</span>
          <span style={styles.c}>кадры</span>
          <span style={styles.c}>gaps</span>
          <span style={styles.c}>dup</span>
          <span style={styles.c}>late</span>
          <span style={styles.c}>jitter</span>
          <span style={styles.c}>drift</span>
        </div>
        {al.tracks.map((t) => <TrackRow key={t.track_id} t={t} />)}
      </div>

      {canExport && (
        <div style={styles.exportRow}>
          <button type="button" style={styles.exportBtn} onClick={() => setExportOpen(true)}>
            Собрать тестовый WAV
          </button>
          <span style={styles.exportHint}>
            Диагностический экспорт. Многоканальный STT пока не включён.
          </span>
        </div>
      )}

      <MultiChannelExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        meetingId={meetingId}
        ingestState={al}
      />
    </div>
  );
}

function TrackRow({ t }: { t: IngestTrackInfo }) {
  const roleLabel = t.role === 'primary' ? 'основной' : 'второй';
  const sideLabel = t.side_hint === 'self' ? 'мы' : t.side_hint === 'opponent' ? 'не мы' : '';
  return (
    <div style={styles.row}>
      <span style={styles.cTrack}>
        <span style={{ color: t.role === 'primary' ? theme.accent.amber : theme.accent.blue }}>{roleLabel}</span>
        {sideLabel && <span style={styles.side}> · {sideLabel}</span>}
      </span>
      <span style={styles.c}>{t.buffered_frames}/{t.frames_count}</span>
      <span style={{ ...styles.c, color: t.gaps_count ? theme.accent.red : theme.text.primary }}>{t.gaps_count}</span>
      <span style={{ ...styles.c, color: t.duplicates_count ? theme.accent.amber : theme.text.primary }}>{t.duplicates_count}</span>
      <span style={{ ...styles.c, color: t.late_frames ? theme.accent.amber : theme.text.primary }}>{t.late_frames}</span>
      <span style={styles.c}>{Math.round(t.jitter_ms)}мс</span>
      <span style={styles.c}>{Math.round(t.drift_ms)}мс</span>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  panel: { display: 'flex', flexDirection: 'column', gap: 10 },
  note: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, lineHeight: 1.5 },
  common: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '8px 10px', background: theme.bg.input, borderRadius: 8,
  },
  commonLabel: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, letterSpacing: '0.04em' },
  commonValue: { fontFamily: theme.font.mono, fontSize: 12, fontWeight: 600, color: theme.accent.green },
  table: { display: 'flex', flexDirection: 'column', gap: 2 },
  row: {
    display: 'grid', gridTemplateColumns: '1.6fr repeat(6, 1fr)', gap: 4,
    alignItems: 'center', padding: '6px 8px', background: theme.bg.input, borderRadius: 6,
  },
  head: { background: 'transparent' },
  cTrack: { fontFamily: theme.font.mono, fontSize: 11, fontWeight: 600 },
  c: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.primary, textAlign: 'right' as const },
  side: { color: theme.text.muted, fontWeight: 400 },
  exportRow: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' as const, marginTop: 4 },
  exportBtn: {
    padding: '8px 16px', background: theme.accent.amber, border: 'none', borderRadius: 8,
    color: '#080A0F', cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: theme.font.body,
  },
  exportHint: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
};
