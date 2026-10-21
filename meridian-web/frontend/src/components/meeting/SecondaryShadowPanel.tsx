import { useSecondaryShadow } from '../../hooks/useSecondaryShadow';
import { SyncBadge } from './SyncBadge';
import { ShadowMetric } from './ShadowMetric';
import styles from './SecondaryShadowPanel.module.css';

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
    <div className={styles.panel}>
      <div className={styles.note}>
        Это устройство пишет ВТОРОЙ аудиоканал встречи для будущего разделения по говорящим.
        Пока канал только записывается в shadow-режиме — речь в текст он не превращает
        (это делает основное устройство).
      </div>

      <div className={styles.sideRow}>
        <span className={styles.label}>Рядом с:</span>
        <button type="button" className={side === 'self' ? styles.sideOnSelf : styles.sideOff}
          onClick={() => setSideHint('self')}>Нами</button>
        <button type="button" className={side === 'opponent' ? styles.sideOnOpp : styles.sideOff}
          onClick={() => setSideHint('opponent')}>Другой стороной</button>
      </div>

      <div className={styles.meterTrack}>
        <div className={styles.meterFill} style={{ transform: `scaleX(${pct / 100})` }} />
      </div>

      {active && diag && (
        <div className={styles.diagGrid}>
          <ShadowMetric label="чанков" value={String(diag.chunks_count)} />
          <ShadowMetric label="буфер" value={`${(diag.estimated_buffer_ms / 1000).toFixed(1)} с`} />
          <ShadowMetric label="пропуски" value={String(diag.gaps_count)}
            warn={diag.gaps_count > 0} />
          <ShadowMetric label="отброшено" value={String(diag.dropped_chunks)}
            warn={diag.dropped_chunks > 0} />
          <ShadowMetric label="drift" value={`${Math.round(diag.drift_ms)} мс`} />
          <ShadowMetric label="лаг пакета"
            value={diag.last_packet_age_ms != null ? `${diag.last_packet_age_ms} мс` : '—'}
            warn={(diag.last_packet_age_ms ?? 0) > 1500} />
          <ShadowMetric label="частота"
            value={diag.sample_rate ? `${Math.round(diag.sample_rate / 1000)}к` : '—'} />
          <ShadowMetric label="кодек" value={diag.codec ?? '—'} />
        </div>
      )}

      <div className={styles.controls}>
        {active ? (
          <button type="button" className={styles.stopBtn} onClick={stop}>Остановить второй канал</button>
        ) : (
          <button type="button" className={styles.startBtn} onClick={() => void start()} disabled={meetingId == null}>
            Включить второй канал
          </button>
        )}
        <span className={styles.status}>{statusText}</span>
        {active && <SyncBadge sync={sync} />}
      </div>

      {meetingId == null && <div className={styles.hint}>Сначала откройте встречу.</div>}
      {error && <div className={styles.error}>{error}</div>}
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  idle: 'ожидание',
  recording: 'идёт запись канала…',
  stale: 'нет пакетов (проверьте связь)',
  error: 'ошибка канала',
};
