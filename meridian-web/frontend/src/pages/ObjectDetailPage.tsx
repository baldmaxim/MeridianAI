import { useState, useEffect } from 'react';
import { theme } from '../styles/theme';
import { getObject } from '../api/objects';
import { listMeetings } from '../api/history';
import { apiErrorMessage } from '../lib/apiError';
import type { ProjectObject, MeetingListItem } from '../types';

interface Props {
  objectId: number;
  onBack: () => void;
  onOpenMeeting: (id: number) => void;
  onNewMeeting: (obj: ProjectObject) => void;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' }) + ' ' +
    d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

export function ObjectDetailPage({ objectId, onBack, onOpenMeeting, onNewMeeting }: Props) {
  const [object, setObject] = useState<ProjectObject | null>(null);
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true); setError('');
      try {
        const [obj, ms] = await Promise.all([getObject(objectId), listMeetings({ object_id: objectId, include_active: true })]);
        if (cancelled) return;
        setObject(obj);
        setMeetings(ms);
      } catch (e) {
        if (!cancelled) setError(apiErrorMessage(e, 'Не удалось загрузить объект'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [objectId]);

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button onClick={onBack} style={styles.backBtn}>&larr; К объектам</button>
        <span style={styles.topTitle}>{object?.name || 'ОБЪЕКТ'}</span>
        {object && (
          <button style={styles.newBtn} onClick={() => onNewMeeting(object)}>+ Новая встреча</button>
        )}
      </div>

      {loading && <div style={styles.muted}>Загрузка…</div>}
      {error && <div style={styles.error}>{error}</div>}

      {object && (
        <div style={styles.infoCard}>
          <div style={styles.infoRow}><span style={styles.infoLabel}>Заказчик</span><span style={styles.infoVal}>{object.customer_name || '—'}</span></div>
          {object.address && <div style={styles.infoRow}><span style={styles.infoLabel}>Адрес</span><span style={styles.infoVal}>{object.address}</span></div>}
          {object.description && <div style={styles.infoRow}><span style={styles.infoLabel}>Описание</span><span style={styles.infoVal}>{object.description}</span></div>}
        </div>
      )}

      {object && (
        <div style={styles.sectionTitle}>Встречи ({meetings.length})</div>
      )}

      {!loading && object && meetings.length === 0 && (
        <div style={styles.muted}>По объекту ещё нет встреч. Создайте первую — «+ Новая встреча».</div>
      )}

      <div style={styles.list}>
        {meetings.map((m) => (
          <button key={m.id} style={styles.card} onClick={() => onOpenMeeting(m.id)}>
            <div style={styles.cardTop}>
              <div style={styles.cardTitle}>{m.title || m.meeting_topic || 'Без названия'}</div>
              <div style={styles.cardDate}>{fmtDate(m.started_at)}</div>
            </div>
            {(m.micro_summary || m.meeting_topic) && (
              <div style={styles.cardSummary}>{m.micro_summary || m.meeting_topic}</div>
            )}
            <div style={styles.badges}>
              {m.status && <span style={styles.badge}>{m.status}</span>}
              {m.suggestion_count > 0 && <span style={styles.badge}>{m.suggestion_count} подсказок</span>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'auto', padding: '20px 24px', gap: 14 },
  topBar: {
    display: 'flex', alignItems: 'center', gap: 16, paddingBottom: 12,
    borderBottom: `1px solid ${theme.border.default}`, flexShrink: 0, flexWrap: 'wrap' as const,
  },
  backBtn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 16px',
    background: 'transparent', border: `1px solid ${theme.accent.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em', flexShrink: 0,
  },
  topTitle: {
    fontFamily: theme.font.heading, fontSize: 15, fontWeight: 800,
    letterSpacing: '0.04em', color: theme.text.primary, flex: 1,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  newBtn: {
    padding: '8px 18px', background: theme.accent.amber, border: 'none', borderRadius: 8,
    color: '#080A0F', cursor: 'pointer', fontSize: 13, fontWeight: 600,
    fontFamily: theme.font.body, whiteSpace: 'nowrap',
  },
  infoCard: {
    background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12,
    padding: 16, display: 'flex', flexDirection: 'column', gap: 10,
  },
  infoRow: { display: 'flex', flexDirection: 'column', gap: 2 },
  infoLabel: {
    fontFamily: theme.font.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.1em',
    textTransform: 'uppercase' as const, color: theme.text.muted,
  },
  infoVal: { fontFamily: theme.font.body, fontSize: 13, color: theme.text.primary, whiteSpace: 'pre-wrap' as const },
  sectionTitle: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 12,
    letterSpacing: '0.1em', textTransform: 'uppercase' as const, color: theme.text.secondary, marginTop: 4,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 10 },
  card: {
    display: 'flex', flexDirection: 'column', gap: 6, padding: 14, textAlign: 'left' as const,
    background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12,
    color: theme.text.primary, cursor: 'pointer', fontFamily: theme.font.body,
  },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10 },
  cardTitle: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 14, flex: 1, minWidth: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  cardDate: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, flexShrink: 0 },
  cardSummary: {
    fontSize: 12, color: theme.text.secondary, overflow: 'hidden', textOverflow: 'ellipsis',
    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const,
  },
  badges: { display: 'flex', gap: 6, flexWrap: 'wrap' as const, marginTop: 2 },
  badge: {
    padding: '2px 8px', background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`,
    borderRadius: 4, fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted, textTransform: 'uppercase' as const,
  },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 13, padding: '12px 0' },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 13, padding: '8px 0' },
};
