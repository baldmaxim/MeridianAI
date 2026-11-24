import { useState, useEffect } from 'react';
import { Collapse } from '../common';
import { getFinalizationStatus, getMeetingProtocol, retryFinalization } from '../../api/finalization';
import { ProtocolView } from './ProtocolView';
import type { FinalizationStatus, MeetingProtocol } from '../../types';
import styles from './ProtocolSection.module.css';
import { cx } from '../../utils/cx';

const POLL_INTERVAL_MS = 3000;

interface IProtocolSectionProps {
  meetingId: number;
  /** Смена значения — перезапросить статус (например, после пересборки протокола). */
  refreshKey?: number;
}

/** Секция протокола для страницы деталей встречи (история): статус, опрос пока идёт сборка, просмотр. */
export function ProtocolSection({ meetingId, refreshKey = 0 }: IProtocolSectionProps) {
  const [status, setStatus] = useState<FinalizationStatus>('not_started');
  const [protocol, setProtocol] = useState<MeetingProtocol | null>(null);
  const [open, setOpen] = useState(false);
  const [pollTick, setPollTick] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const s = await getFinalizationStatus(meetingId);
        if (!alive) return;
        setStatus(s.status);
        if (s.status === 'queued' || s.status === 'running') {
          timer = setTimeout(load, POLL_INTERVAL_MS);
        } else if ((s.status === 'completed' || s.status === 'partial') && s.has_protocol) {
          try {
            const p = await getMeetingProtocol(meetingId);
            if (alive) setProtocol(p);
          } catch { /* ignore */ }
        }
      } catch { /* статус недоступен — секция протокола не показывается */ }
    };
    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [meetingId, refreshKey, pollTick]);

  if (status === 'not_started') return null;

  const tone = status === 'completed' ? styles.toneGreen : status === 'error' ? styles.toneRed
    : status === 'partial' ? styles.toneAmber : styles.toneBlue;
  const label = status === 'completed' ? 'Протокол готов' : status === 'error' ? 'Ошибка протокола'
    : status === 'partial' ? 'Протокол (частично)' : 'Формируется протокол…';

  return (
    <div className={styles.wrap}>
      <div className={styles.bar}>
        <span className={cx(styles.badge, tone)}>{label}</span>
        {protocol && (
          <button className={styles.toggle} onClick={() => setOpen((v) => !v)}>
            {open ? 'Скрыть протокол' : 'Открыть протокол'}
          </button>
        )}
        {status === 'error' && (
          <button className={styles.toggle} onClick={() => retryFinalization(meetingId).then((s) => { setStatus(s.status); setPollTick((t) => t + 1); })}>
            Повторить
          </button>
        )}
      </div>
      {protocol && (
        <Collapse open={open} className={styles.body}><ProtocolView p={protocol} /></Collapse>
      )}
    </div>
  );
}
