import { useState, useEffect } from 'react';
import { MobileLayout } from '../../components/mobile/MobileLayout';
import { listMobileMeetings } from '../../api/mobile';
import { navigate } from '../../lib/navigation';
import { apiErrorMessage } from '../../lib/apiError';
import type { MobileMeetingListItem } from '../../types';
import styles from './MobileMeetingsPage.module.css';
import { cx } from '../../utils/cx';
import { TextInput } from '../../components/common';

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

  // Перезагрузка только при смене фильтра; поиск по тексту запускается кнопкой/Enter
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [filter]);

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
      <div className={styles.searchRow}>
        <TextInput
          className={styles.searchField}
          inputClassName={styles.search}
          placeholder="Поиск по названию/теме…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onClear={() => setQ('')}
          clearLabel="поиск"
          onKeyDown={(e) => { if (e.key === 'Enter') load(); }}
        />
        <button className={styles.searchBtn} onClick={load}>Найти</button>
      </div>

      <div className={styles.chips}>
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={cx(filter === f.key ? styles.chipActive : styles.chip)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && <div className={styles.muted}>Загрузка…</div>}
      {error && <div className={styles.error}>{error}</div>}
      {!loading && !error && items.length === 0 && <div className={styles.muted}>Нет встреч</div>}

      <div className={styles.list}>
        {items.map((m) => (
          <button key={m.id} className={styles.card} onClick={() => navigate(`/mobile/meetings/${m.id}`)}>
            <div className={styles.cardTop}>
              <div className={styles.cardTitle}>{m.title || m.meeting_topic || 'Без названия'}</div>
              <div className={styles.cardDate}>{fmtDate(m.started_at)}</div>
            </div>
            <div className={styles.cardMeta}>
              {m.customer_name && <span>🏢 {m.customer_name}</span>}
              {m.object_name && <span>📍 {m.object_name}</span>}
            </div>
            {(m.micro_summary || m.meeting_topic) && (
              <div className={styles.cardSummary}>{m.micro_summary || m.meeting_topic}</div>
            )}
            <div className={styles.badges}>
              {m.is_live && <span className={styles.badgeLive}>● LIVE</span>}
              {m.status && <span className={styles.badge}>{m.status}</span>}
              <span className={cx(m.can_record ? styles.badgeRec : styles.badgeView)}>
                {m.can_record ? 'можно записывать' : 'только просмотр'}
              </span>
            </div>
          </button>
        ))}
      </div>
    </MobileLayout>
  );
}
