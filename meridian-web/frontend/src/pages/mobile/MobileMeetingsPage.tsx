import { useState, useEffect } from 'react';
import { theme } from '../../styles/theme';
import { MobileLayout } from '../../components/mobile/MobileLayout';
import { listMobileMeetings } from '../../api/mobile';
import { navigate } from '../../lib/navigation';
import { apiErrorMessage } from '../../lib/apiError';
import type { MobileMeetingListItem } from '../../types';

interface Props {
  userName?: string;
  onLogout: () => void;
}

type Filter = 'all' | 'live' | 'draft' | 'finalized';

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'Все' },
  { key: 'live', label: 'Live' },
  { key: 'draft', label: 'Черновики' },
  { key: 'finalized', label: 'Завершённые' },
];

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) + ' ' +
    d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

export function MobileMeetingsPage({ userName, onLogout }: Props) {
  const [items, setItems] = useState<MobileMeetingListItem[]>([]);
  const [filter, setFilter] = useState<Filter>('all');
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filter]);

  async function load() {
    setLoading(true); setError('');
    try {
      const data = await listMobileMeetings({
        q: q.trim() || undefined,
        only_live: filter === 'live' || undefined,
        status: filter === 'draft' ? 'active' : filter === 'finalized' ? 'finalized' : undefined,
      });
      setItems(data);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось загрузить встречи'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <MobileLayout title="ВСТРЕЧИ" userName={userName} onLogout={onLogout}>
      <div style={styles.searchRow}>
        <input
          style={styles.search}
          placeholder="Поиск по названию/теме…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') load(); }}
        />
        <button style={styles.searchBtn} onClick={load}>Найти</button>
      </div>

      <div style={styles.chips}>
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            style={filter === f.key ? styles.chipActive : styles.chip}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && <div style={styles.muted}>Загрузка…</div>}
      {error && <div style={styles.error}>{error}</div>}
      {!loading && !error && items.length === 0 && <div style={styles.muted}>Нет встреч</div>}

      <div style={styles.list}>
        {items.map((m) => (
          <button key={m.id} style={styles.card} onClick={() => navigate(`/mobile/meetings/${m.id}`)}>
            <div style={styles.cardTop}>
              <div style={styles.cardTitle}>{m.title || m.meeting_topic || 'Без названия'}</div>
              <div style={styles.cardDate}>{fmtDate(m.started_at)}</div>
            </div>
            <div style={styles.cardMeta}>
              {m.customer_name && <span>🏢 {m.customer_name}</span>}
              {m.object_name && <span>📍 {m.object_name}</span>}
            </div>
            {(m.micro_summary || m.meeting_topic) && (
              <div style={styles.cardSummary}>{m.micro_summary || m.meeting_topic}</div>
            )}
            <div style={styles.badges}>
              {m.is_live && <span style={styles.badgeLive}>● LIVE</span>}
              {m.status && <span style={styles.badge}>{m.status}</span>}
              <span style={m.can_record ? styles.badgeRec : styles.badgeView}>
                {m.can_record ? 'можно записывать' : 'только просмотр'}
              </span>
            </div>
          </button>
        ))}
      </div>
    </MobileLayout>
  );
}

const styles: Record<string, React.CSSProperties> = {
  searchRow: { display: 'flex', gap: 8, marginBottom: 12 },
  search: {
    flex: 1, padding: '10px 12px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 8,
    color: theme.text.primary, fontSize: 14, fontFamily: theme.font.body, outline: 'none',
  },
  searchBtn: {
    padding: '0 16px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 8, color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono,
  },
  chips: { display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' as const },
  chip: {
    padding: '6px 14px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 20, color: theme.text.secondary, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono,
  },
  chipActive: {
    padding: '6px 14px', background: theme.accent.amberGlow, border: `1px solid ${theme.accent.amber}`,
    borderRadius: 20, color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 600,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 10 },
  card: {
    display: 'flex', flexDirection: 'column', gap: 6, padding: 14, textAlign: 'left' as const,
    background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12,
    color: theme.text.primary, cursor: 'pointer', fontFamily: theme.font.body,
  },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10 },
  cardTitle: { fontFamily: theme.font.heading, fontWeight: 700, fontSize: 15, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  cardDate: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, flexShrink: 0 },
  cardMeta: { display: 'flex', gap: 12, flexWrap: 'wrap' as const, fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary },
  cardSummary: { fontSize: 12, color: theme.text.secondary, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const },
  badges: { display: 'flex', gap: 6, flexWrap: 'wrap' as const, marginTop: 2 },
  badge: {
    padding: '2px 8px', background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`,
    borderRadius: 4, fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted, textTransform: 'uppercase' as const,
  },
  badgeLive: {
    padding: '2px 8px', background: 'rgba(255,75,110,0.12)', border: '1px solid rgba(255,75,110,0.3)',
    borderRadius: 4, fontFamily: theme.font.mono, fontSize: 9, color: theme.accent.red, fontWeight: 700,
  },
  badgeRec: {
    padding: '2px 8px', background: 'rgba(46,229,157,0.1)', border: '1px solid rgba(46,229,157,0.25)',
    borderRadius: 4, fontFamily: theme.font.mono, fontSize: 9, color: theme.accent.green,
  },
  badgeView: {
    padding: '2px 8px', background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`,
    borderRadius: 4, fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted,
  },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 13, padding: '12px 0' },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 13, padding: '8px 0' },
};
