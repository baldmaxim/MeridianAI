import { useObserverMic } from '../../hooks/useObserverMic';
import { SyncBadge } from './SyncBadge';
import styles from './ObserverPanel.module.css';

interface ObserverPanelProps {
  meetingId: number | null;
}

// Этап 9: режим «наблюдатель» для второго телефона. Устройство НЕ записывает речь в текст —
// только измеряет громкость локально и подсказывает, к какой стороне относится реплика.
export function ObserverPanel({ meetingId }: ObserverPanelProps) {
  const { active, side, level, error, sync, start, stop, setSideHint } = useObserverMic(meetingId);
  const pct = Math.min(100, Math.round(level * 400));

  return (
    <div className={styles.panel}>
      <div className={styles.note}>
        Положите это устройство рядом с одной из сторон. Он не записывает речь в текст — только громкость,
        чтобы подсказать, чья это реплика. Звук в STT отправляет основное устройство.
      </div>

      <div className={styles.sideRow}>
        <span className={styles.label}>Рядом с:</span>
        <button
          type="button"
          className={side === 'self' ? styles.sideOnSelf : styles.sideOff}
          onClick={() => setSideHint('self')}
        >Нами</button>
        <button
          type="button"
          className={side === 'opponent' ? styles.sideOnOpp : styles.sideOff}
          onClick={() => setSideHint('opponent')}
        >Другой стороной</button>
      </div>

      <div className={styles.meterTrack}>
        <div className={styles.meterFill} style={{ transform: `scaleX(${pct / 100})` }} />
      </div>

      <div className={styles.controls}>
        {active ? (
          <button type="button" className={styles.stopBtn} onClick={stop}>Остановить наблюдение</button>
        ) : (
          <button type="button" className={styles.startBtn} onClick={() => void start()} disabled={meetingId == null}>
            Включить наблюдение
          </button>
        )}
        <span className={styles.status}>{active ? 'идёт измерение уровня…' : 'выключено'}</span>
        {active && <SyncBadge sync={sync} />}
      </div>

      {meetingId == null && <div className={styles.hint}>Сначала откройте встречу.</div>}
      {error && <div className={styles.error}>{error}</div>}
    </div>
  );
}
