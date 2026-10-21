import { useState, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { paths, navTo } from '../lib/navigation';
import { apiErrorMessage } from '../lib/apiError';
import { ObjectCreateModal } from '../components/directory/ObjectCreateModal';
import { useObjects, directoryKeys } from '../hooks/queries/directory';
import { useMeetingsList } from '../hooks/queries/meetings';
import type { ProjectObject } from '../types';
import styles from './ObjectsPage.module.css';
import { cx } from '../utils/cx';
import { TextInput } from '../components/common';

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
    <div className={cx('objects-page', styles.container)}>
      <div className={styles.topBar}>
        <span className={styles.title}>ОБЪЕКТЫ</span>
        <button className={cx('t-btn t-btn-amber', styles.addBtn)} onClick={() => setShowCreate(true)}>+ Объект</button>
      </div>

      {objects.length > 0 && (
        <TextInput
          className="objects-search"
          inputClassName={styles.search}
          placeholder="Поиск по объекту / заказчику…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onClear={() => setQ('')}
          clearLabel="поиск"
        />
      )}

      {loading && <div className={styles.muted}>Загрузка…</div>}
      {error && <div className={styles.error}>{error}</div>}
      {!loading && !error && objects.length === 0 && (
        <div className={styles.empty}>
          <div className={styles.emptyText}>Объектов пока нет</div>
        </div>
      )}
      {!loading && !error && objects.length > 0 && filtered.length === 0 && (
        <div className={styles.muted}>Ничего не найдено</div>
      )}

      <div className={styles.groups}>
        {groups.map(([customer, items]) => {
          const isCollapsed = !!collapsed[customer];
          return (
            <div key={customer} className={styles.group}>
              <button
                className={styles.groupHeader}
                onClick={() => setCollapsed((c) => ({ ...c, [customer]: !c[customer] }))}
                aria-expanded={!isCollapsed}
              >
                <span className={cx(styles.groupChevron, isCollapsed && styles.groupChevronCollapsed)}>▾</span>
                <span className={styles.groupName}>🏢 {customer}</span>
                <span className={styles.groupCount}>{items.length}</span>
              </button>
              {!isCollapsed && (
                <div className={styles.rows}>
                  {items.map((o) => {
                    const count = counts[o.id] || 0;
                    return (
                      <button key={o.id} className={styles.row} {...navTo(paths.objectDetail(o.id), () => onOpenObject(o.id))}>
                        <span className={styles.rowName}>{o.name}</span>
                        {o.address && <span className={styles.rowAddr}>📍 {o.address}</span>}
                        <span className={cx(count > 0 ? styles.countActive : styles.count)}>{pluralMeetings(count)}</span>
                        <span className={styles.chevron}>→</span>
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
