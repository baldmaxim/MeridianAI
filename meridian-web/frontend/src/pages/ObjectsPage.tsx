import { useState, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { theme } from '../styles/theme';
import { paths, navTo } from '../lib/navigation';
import { apiErrorMessage } from '../lib/apiError';
import { ObjectCreateModal } from '../components/directory/ObjectCreateModal';
import { useObjects, directoryKeys } from '../hooks/queries/directory';
import { useMeetingsList } from '../hooks/queries/meetings';
import type { ProjectObject } from '../types';

interface Props {
  onOpenObject: (id: number) => void;
}

function pluralMeetings(n: number): string {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} встреча`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return `${n} встречи`;
  return `${n} встреч`;
}

export function ObjectsPage({ onOpenObject }: Props) {
  const qc = useQueryClient();
  const objectsQuery = useObjects();
  // include_active: активные встречи тоже считаем (иначе у объекта «0 встреч», хотя они есть)
  const meetingsQuery = useMeetingsList({ include_active: true }); // счётчики встреч по объектам
  const objects = objectsQuery.data ?? [];
  const [q, setQ] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const loading = objectsQuery.isPending;
  const error = objectsQuery.error ? apiErrorMessage(objectsQuery.error, 'Не удалось загрузить объекты') : '';

  const counts = useMemo(() => {
    const map: Record<number, number> = {};
    for (const m of meetingsQuery.data ?? []) {
      if (m.object_id != null) map[m.object_id] = (map[m.object_id] || 0) + 1;
    }
    return map;
  }, [meetingsQuery.data]);

  const term = q.trim().toLowerCase();
  const filtered = term
    ? objects.filter((o) =>
        o.name.toLowerCase().includes(term) ||
        (o.customer_name || '').toLowerCase().includes(term) ||
        (o.address || '').toLowerCase().includes(term))
    : objects;

  // Группировка по заказчику (fallback — «Без заказчика»), группы по алфавиту.
  const groups = (() => {
    const m = new Map<string, ProjectObject[]>();
    for (const o of filtered) {
      const key = o.customer_name?.trim() || 'Без заказчика';
      const arr = m.get(key);
      if (arr) arr.push(o); else m.set(key, [o]);
    }
    return Array.from(m.entries()).sort((a, b) => a[0].localeCompare(b[0], 'ru'));
  })();

  return (
    <div className="objects-page" style={styles.container}>
      <div style={styles.topBar}>
        <span style={styles.title}>ОБЪЕКТЫ</span>
        <button className="t-btn t-btn-amber" style={styles.addBtn} onClick={() => setShowCreate(true)}>+ Объект</button>
      </div>

      {objects.length > 0 && (
        <input
          className="objects-search"
          style={styles.search}
          placeholder="Поиск по объекту / заказчику…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      )}

      {loading && <div style={styles.muted}>Загрузка…</div>}
      {error && <div style={styles.error}>{error}</div>}
      {!loading && !error && objects.length === 0 && (
        <div style={styles.empty}>
          <div style={styles.emptyText}>Объектов пока нет</div>
        </div>
      )}
      {!loading && !error && objects.length > 0 && filtered.length === 0 && (
        <div style={styles.muted}>Ничего не найдено</div>
      )}

      <style>{`
        .obj-group-chevron { transition: transform 0.18s ease; }
        @media (prefers-reduced-motion: reduce) { .obj-group-chevron { transition: none; } }
      `}</style>

      <div style={styles.groups}>
        {groups.map(([customer, items]) => {
          const isCollapsed = !!collapsed[customer];
          return (
            <div key={customer} style={styles.group}>
              <button
                style={styles.groupHeader}
                onClick={() => setCollapsed((c) => ({ ...c, [customer]: !c[customer] }))}
                aria-expanded={!isCollapsed}
              >
                <span className="obj-group-chevron" style={{ ...styles.groupChevron, transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)' }}>▾</span>
                <span style={styles.groupName}>🏢 {customer}</span>
                <span style={styles.groupCount}>{items.length}</span>
              </button>
              {!isCollapsed && (
                <div style={styles.rows}>
                  {items.map((o) => {
                    const count = counts[o.id] || 0;
                    return (
                      <button key={o.id} style={styles.row} {...navTo(paths.objectDetail(o.id), () => onOpenObject(o.id))}>
                        <span style={styles.rowName}>{o.name}</span>
                        {o.address && <span style={styles.rowAddr}>📍 {o.address}</span>}
                        <span style={count > 0 ? styles.countActive : styles.count}>{pluralMeetings(count)}</span>
                        <span style={styles.chevron}>→</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <ObjectCreateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => { setShowCreate(false); qc.invalidateQueries({ queryKey: directoryKeys.objectsAll }); }}
      />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'auto', padding: '20px 24px', gap: 16 },
  topBar: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' as const },
  title: {
    fontFamily: theme.font.heading, fontWeight: 800, fontSize: 18,
    letterSpacing: '0.06em', color: theme.text.primary,
  },
  search: {
    width: '100%', padding: '9px 14px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 8,
    color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  addBtn: {
    padding: '9px 16px', background: theme.accent.amber, border: 'none',
    borderRadius: 8, color: '#080A0F', cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 700, whiteSpace: 'nowrap',
  },
  groups: { display: 'flex', flexDirection: 'column', gap: 18 },
  group: { display: 'flex', flexDirection: 'column', gap: 8 },
  groupHeader: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '6px 4px',
    background: 'transparent', border: 'none', cursor: 'pointer',
    textAlign: 'left' as const, width: '100%',
  },
  groupChevron: { color: theme.accent.amber, fontSize: 12, display: 'inline-block', width: 12 },
  groupName: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 13,
    letterSpacing: '0.04em', color: theme.text.primary, flex: 1, minWidth: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  groupCount: {
    fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted,
    background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`,
    borderRadius: 10, padding: '1px 8px', flexShrink: 0,
  },
  rows: { display: 'flex', flexDirection: 'column', gap: 6 },
  row: {
    display: 'flex', alignItems: 'center', gap: 12, width: '100%',
    padding: '10px 14px', textAlign: 'left' as const,
    background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 10,
    color: theme.text.primary, cursor: 'pointer', fontFamily: theme.font.body,
  },
  rowName: {
    fontFamily: theme.font.body, fontWeight: 600, fontSize: 14, flex: 1, minWidth: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  rowAddr: {
    fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 220, flexShrink: 1,
  },
  count: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, flexShrink: 0, whiteSpace: 'nowrap' as const },
  countActive: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.green, fontWeight: 600, flexShrink: 0, whiteSpace: 'nowrap' as const },
  chevron: { color: theme.accent.amber, fontSize: 16, flexShrink: 0 },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 13, padding: '12px 0' },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 13, padding: '8px 0' },
  empty: { display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'flex-start', padding: '24px 0' },
  emptyText: { color: theme.text.secondary, fontFamily: theme.font.body, fontSize: 14 },
};
