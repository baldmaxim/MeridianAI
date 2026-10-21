import { useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { MultiChannelExportModal } from './MultiChannelExportModal';
import { IngestTrackRow } from './IngestTrackRow';
import styles from './IngestPanel.module.css';

// Этап 9.3: монитор multi-source ingest. Показывает, что backend свёл аудиоисточники
// к ОДНОЙ server timeline: общий диапазон canonical-фреймов (один и тот же интервал
// для всех треков) + per-track метрики качества (gaps/dup/late/jitter/drift).
// Пока без mux/STT для secondary — только выравнивание.
export function IngestPanel() {
  const al = useMeetingStore((s) => s.ingestAlignment);
  const meetingId = useMeetingStore((s) => s.currentMeetingId);
  const [exportOpen, setExportOpen] = useState(false);

  if (!al || al.tracks.length === 0) {
    return <div className={styles.note}>Второй источник ещё не подключён. Здесь появится выравнивание
      каналов по единой временной шкале, когда пишет основной и/или второй канал.</div>;
  }

  const canExport = meetingId != null && al.tracks.some((t) => t.buffered_frames > 0);

  const aligned = al.common_lo != null && al.common_hi != null
    ? `${al.common_hi - al.common_lo + 1} фреймов (#${al.common_lo}–${al.common_hi})`
    : '—';

  return (
    <div className={styles.panel}>
      <div className={styles.note}>
        Backend сводит источники к единой шкале (кадр = {al.frame_ms} мс). Совпадающий
        диапазон фреймов = общий временной интервал каналов.
      </div>
      <div className={styles.common}>
        <span className={styles.commonLabel}>общий выровненный интервал</span>
        <span className={styles.commonValue}>{aligned}</span>
      </div>
      <div className={styles.table}>
        <div className={`${styles.row} ${styles.head}`}>
          <span className={styles.cTrack}>канал</span>
          <span className={styles.c}>кадры</span>
          <span className={styles.c}>gaps</span>
          <span className={styles.c}>dup</span>
          <span className={styles.c}>late</span>
          <span className={styles.c}>jitter</span>
          <span className={styles.c}>drift</span>
        </div>
        {al.tracks.map((t) => <IngestTrackRow key={t.track_id} t={t} />)}
      </div>

      {canExport && (
        <div className={styles.exportRow}>
          <button type="button" className={styles.exportBtn} onClick={() => setExportOpen(true)}>
            Собрать тестовый WAV
          </button>
          <span className={styles.exportHint}>
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
