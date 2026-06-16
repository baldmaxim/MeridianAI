import { useState, useEffect } from 'react';
import { theme } from '../styles/theme';
import { listObjects } from '../api/objects';
import { listMeetings } from '../api/history';
import { apiErrorMessage } from '../lib/apiError';
import type { ProjectObject } from '../types';

interface Props {
  onOpenObject: (id: number) => void;
  onGoDirectory: () => void;
}

function pluralMeetings(n: number): string {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} встреча`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return `${n} встречи`;
  return `${n} встреч`;
}

export function ObjectsPage({ onOpenObject, onGoDirectory }: Props) {
  const [objects, setObjects] = useState<ProjectObject[]>([]);
  const [counts, setCounts] = useState<Record<number, number>>({});
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true); setError('');
      try {
        const [objs, meetings] = await Promise.all([listObjects(), listMeetings()]);
        if (cancelled) return;
        const map: Record<number, number> = {};
        for (const m of meetings) {
          if (m.object_id != null) map[m.object_id] = (map[m.object_id] || 0) + 1;
        }
        setObjects(objs);
        setCounts(map);
      } catch (e) {
        if (!cancelled) setError(apiErrorMessage(e, 'Не удалось загрузить объекты'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const term = q.trim().toLowerCase();
  const filtered = term
    ? objects.filter((o) =>
        o.name.toLowerCase().includes(term) ||
        (o.customer_name || '').toLowerCase().includes(term) ||
        (o.address || '').toLowerCase().includes(term))
    : objects;

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <span style={styles.title}>ОБЪЕКТЫ</span>
        <input
          style={styles.search}
          placeholder="Поиск по объекту / заказчику…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button style={styles.addBtn} onClick={onGoDirectory}>+ Объект</button>
      </div>

      {loading && <div style={styles.muted}>Загрузка…</div>}
      {error && <div style={styles.error}>{error}</div>}
      {!loading && !error && objects.length === 0 && (
        <div style={styles.empty}>
          <div style={styles.emptyText}>Объектов пока нет</div>
          <button style={styles.addBtn} onClick={onGoDirectory}>Создать в справочниках</button>
        </div>
      )}
      {!loading && !error && objects.length > 0 && filtered.length === 0 && (
        <div style={styles.muted}>Ничего не найдено</div>
      )}

      <div style={styles.grid}>
        {filtered.map((o) => {
          const count = counts[o.id] || 0;
          return (
            <button key={o.id} style={styles.card} onClick={() => onOpenObject(o.id)}>
              <div style={styles.cardName}>{o.name}</div>
              <div style={styles.cardMeta}>
                <span>🏢 {o.customer_name || '—'}</span>
                {o.address && <span style={styles.cardAddr}>📍 {o.address}</span>}
              </div>
              <div style={styles.cardFoot}>
                <span style={count > 0 ? styles.countActive : styles.count}>{pluralMeetings(count)}</span>
                <span style={styles.chevron}>→</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'auto', padding: '20px 24px', gap: 16 },
  topBar: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' as const },
  title: {
    fontFamily: theme.font.heading, fontWeight: 800, fontSize: 18,
    letterSpacing: '0.06em', color: theme.text.primary,
  },
  search: {
    flex: 1, minWidth: 200, padding: '9px 14px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 8,
    color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  addBtn: {
    padding: '9px 16px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 8, color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 600, whiteSpace: 'nowrap',
  },
  grid: { display: 'flex', flexWrap: 'wrap' as const, gap: 12, alignContent: 'flex-start' },
  card: {
    display: 'flex', flexDirection: 'column', gap: 8, padding: 16, textAlign: 'left' as const,
    flex: '1 1 280px', maxWidth: 420, minWidth: 0,
    background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12,
    color: theme.text.primary, cursor: 'pointer', fontFamily: theme.font.body,
  },
  cardName: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 15,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  cardMeta: {
    display: 'flex', gap: 12, flexWrap: 'wrap' as const,
    fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary,
  },
  cardAddr: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200 },
  cardFoot: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 2 },
  count: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  countActive: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.green, fontWeight: 600 },
  chevron: { color: theme.accent.amber, fontSize: 16 },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 13, padding: '12px 0' },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 13, padding: '8px 0' },
  empty: { display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'flex-start', padding: '24px 0' },
  emptyText: { color: theme.text.secondary, fontFamily: theme.font.body, fontSize: 14 },
};
