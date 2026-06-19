import { useState, useEffect } from 'react';
import { theme } from '../../styles/theme';
import { Collapse } from '../common';
import { getFinalizationStatus, getMeetingProtocol, retryFinalization } from '../../api/finalization';
import { ProtocolView } from './ProtocolView';
import type { FinalizationStatus, MeetingProtocol } from '../../types';

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
    }).catch(() => {});
    return () => { alive = false; };
  }, [meetingId]);

  if (status === 'not_started') return null;

  const color = status === 'completed' ? theme.accent.green : status === 'error' ? theme.accent.red
    : status === 'partial' ? theme.accent.amber : theme.accent.blue;
  const label = status === 'completed' ? 'Протокол готов' : status === 'error' ? 'Ошибка протокола'
    : status === 'partial' ? 'Протокол (частично)' : 'Формируется протокол…';

  return (
    <div style={styles.wrap}>
      <div style={styles.bar}>
        <span style={{ ...styles.badge, color, borderColor: color }}>{label}</span>
        {protocol && (
          <button style={styles.toggle} onClick={() => setOpen((v) => !v)}>
            {open ? 'Скрыть протокол' : 'Открыть протокол'}
          </button>
        )}
        {status === 'error' && (
          <button style={styles.toggle} onClick={() => retryFinalization(meetingId).then((s) => setStatus(s.status))}>
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

const styles: Record<string, React.CSSProperties> = {
  wrap: { display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 12 },
  bar: { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' as const },
  badge: { padding: '3px 10px', border: '1px solid', borderRadius: 12, fontFamily: theme.font.mono, fontSize: 10 },
  toggle: { padding: '6px 14px', background: 'transparent', border: `1px solid ${theme.border.amber}`, borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono },
};
