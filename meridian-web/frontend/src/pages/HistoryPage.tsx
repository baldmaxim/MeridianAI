import { useState } from 'react';
import type { FC } from 'react';
import {
  useMeetingsList, useFinalizeMeeting, useRetryFinalization, useBatchDeleteMeetings,
} from '../hooks/queries/meetings';
import { useCustomers, useObjects } from '../hooks/queries/directory';
import { HistoryBatchBar } from './history/HistoryBatchBar';
import { HistoryFilters } from './history/HistoryFilters';
import { HistoryViewTabs } from './history/HistoryViewTabs';
import type { THistoryView } from './history/HistoryViewTabs';
import { MeetingCard } from './history/MeetingCard';
import styles from './HistoryPage.module.css';

interface IHistoryPageProps {
  onBack: () => void;
  onSelectMeeting: (id: number) => void;
}

export const HistoryPage: FC<IHistoryPageProps> = ({ onBack, onSelectMeeting }) => {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirmBatch, setConfirmBatch] = useState(false);
  const [finalizingId, setFinalizingId] = useState<number | null>(null);

  // Завершённые (по умолчанию) | Черновики (active) | Все
  const [view, setView] = useState<THistoryView>('finished');

  // Этап 1 MVP: фильтры по заказчику/объекту + поиск (поиск применяется по кнопке/Enter)
  const [filterCustomerId, setFilterCustomerId] = useState<number | ''>('');
  const [filterObjectId, setFilterObjectId] = useState<number | ''>('');
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');

  const { data: customers = [] } = useCustomers();
  const { data: objects = [] } = useObjects(filterCustomerId === '' ? undefined : filterCustomerId);

  const meetingsQuery = useMeetingsList({
    customer_id: filterCustomerId === '' ? undefined : filterCustomerId,
    object_id: filterObjectId === '' ? undefined : filterObjectId,
    q: appliedSearch || undefined,
    include_active: view !== 'finished',
    status: view === 'drafts' ? 'active' : undefined,
  });
  const meetings = meetingsQuery.data ?? [];
  const loading = meetingsQuery.isPending;
  const error = meetingsQuery.isError ? 'Ошибка загрузки истории' : '';

  const finalizeMut = useFinalizeMeeting();
  const retryMut = useRetryFinalization();
  const batchDeleteMut = useBatchDeleteMeetings();
  const deleting = batchDeleteMut.isPending;

  const applySearch = () => setAppliedSearch(search.trim());

  function onCustomerChange(v: number | '') {
    setFilterCustomerId(v);
    setFilterObjectId(''); // сброс объекта при смене заказчика
  }

  async function handleFinalize(id: number) {
    if (finalizingId != null) return;
    setFinalizingId(id);
    try {
      await finalizeMut.mutateAsync(id);
    } catch { /* ignore */ } finally {
      setFinalizingId(null);
    }
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === meetings.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(meetings.map((m) => m.id)));
    }
  }

  async function handleBatchDelete() {
    if (selected.size === 0 || deleting) return;
    try {
      await batchDeleteMut.mutateAsync([...selected]);
      setSelected(new Set());
      setConfirmBatch(false);
    } catch { /* ignore */ }
  }

  async function handleRetry(id: number) {
    try {
      await retryMut.mutateAsync(id);
    } catch { /* ignore */ }
  }

  return (
    <div className={`history-container ${styles.container}`}>
      {/* Top bar */}
      <div className={styles.topBar}>
        <button onClick={onBack} className={`t-btn ${styles.backBtn}`}>&larr; К переговорам</button>
        <span className={styles.topTitle}>ИСТОРИЯ ВСТРЕЧ</span>
        <span className={styles.topMeta}>{meetings.length} встреч</span>
      </div>

      {/* Header */}
      <div className={styles.headerRow}>
        <div>
          <h2 className={styles.title}>
            Архив<span className={styles.titleAccent}> встреч</span>
          </h2>
          <div className={styles.subtitle}>Сохраненные встречи с транскрипцией и подсказками</div>
        </div>

        {/* Batch controls */}
        {meetings.length > 0 && (
          <HistoryBatchBar
            total={meetings.length}
            selectedCount={selected.size}
            confirming={confirmBatch}
            deleting={deleting}
            onToggleAll={toggleAll}
            onAskConfirm={() => setConfirmBatch(true)}
            onCancelConfirm={() => setConfirmBatch(false)}
            onDelete={handleBatchDelete}
          />
        )}
      </div>

      {/* Вид: завершённые / черновики / все */}
      <HistoryViewTabs view={view} onChange={setView} />

      {/* Фильтры (Этап 1 MVP) */}
      <HistoryFilters
        customerOptions={customers.map((c) => ({ value: String(c.id), label: c.name }))}
        objectOptions={objects.map((o) => ({ value: String(o.id), label: o.name }))}
        customerId={filterCustomerId}
        objectId={filterObjectId}
        search={search}
        onCustomerChange={onCustomerChange}
        onObjectChange={setFilterObjectId}
        onSearchChange={setSearch}
        onApplySearch={applySearch}
      />

      {/* Content */}
      {loading && <div className={styles.empty}>Загрузка...</div>}
      {error && <div className={`${styles.empty} ${styles.emptyError}`}>{error}</div>}

      {!loading && !error && meetings.length === 0 && (
        <div className={styles.emptyCard}>
          <div className={styles.emptyIcon}>&#9711;</div>
          <div className={styles.emptyText}>
            {view === 'drafts' ? 'Нет черновиков' : view === 'all' ? 'Нет встреч' : 'Нет завершённых встреч'}
          </div>
          <div className={styles.emptyHint}>
            {view === 'finished' ? 'Встречи появятся здесь после завершения сессии' : 'Незавершённые встречи (запись с устройства/ПК) показываются здесь'}
          </div>
        </div>
      )}

      {!loading && meetings.length > 0 && (
        <div className={styles.list}>
          {meetings.map((m) => (
            <MeetingCard
              key={m.id}
              meeting={m}
              selected={selected.has(m.id)}
              finalizing={finalizingId === m.id}
              onToggleSelect={toggleSelect}
              onOpen={onSelectMeeting}
              onFinalize={handleFinalize}
              onRetry={handleRetry}
            />
          ))}
        </div>
      )}
    </div>
  );
};
