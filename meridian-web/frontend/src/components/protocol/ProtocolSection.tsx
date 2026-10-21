import { useState, useEffect } from 'react';
import { Collapse } from '../common';
import { getFinalizationStatus, getMeetingProtocol, retryFinalization } from '../../api/finalization';
import { ProtocolView } from './ProtocolView';
import type { FinalizationStatus, MeetingProtocol } from '../../types';
import styles from './ProtocolSection.module.css';
import { cx } from '../../utils/cx';

/** Read-only секция протокола для страницы деталей встречи (история). */
export function ProtocolSection({ meetingId }: { meetingId: number }) {
  const [status, setStatus] = useState<FinalizationStatus>('not_started');
  const [protocol, setProtocol] = useState<MeetingProtocol | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    getFinalizationStatus(meetingId).then(async (s) => {
      if (!alive) return;
      setStatus(s.status);
      if ((s.status === 'completed' || s.status === 'partial') && s.has_protocol) {
        try { setProtocol(await getMeetingProtocol(meetingId)); } catch { /* ignore */ }
      }
    }).catch(() => { /* статус недоступен — секция протокола не показывается */ });
    return () => { alive = false; };
  }, [meetingId]);

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
          <button className={styles.toggle} onClick={() => retryFinalization(meetingId).then((s) => setStatus(s.status))}>
            Повторить
          </button>
        )}
      </div>
      {protocol && (
        <Collapse open={open}><ProtocolView p={protocol} /></Collapse>
      )}
    </div>
  );
}
