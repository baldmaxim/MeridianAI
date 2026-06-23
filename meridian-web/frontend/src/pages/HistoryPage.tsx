import { useState } from 'react';
import { theme } from '../styles/theme';
import { Select } from '../components/common';
import {
  useMeetingsList, useFinalizeMeeting, useRetryFinalization, useBatchDeleteMeetings,
} from '../hooks/queries/meetings';
import { useCustomers, useObjects } from '../hooks/queries/directory';
import { meetingDisplayName } from '../lib/meetingName';
import { FIN_LABELS, finBadgeStyle, formatDuration } from '../lib/meetingMeta';
import { paths, navTo } from '../lib/navigation';

interface Props {
  onBack: () => void;
  onSelectMeeting: (id: number) => void;
}

const NEGOTIATION_TYPE_LABELS: Record<string, string> = {
  sale: 'Продажа',
  claim: 'Претензия',
  negotiation: 'Переговоры',
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

export function HistoryPage({ onBack, onSelectMeeting }: Props) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirmBatch, setConfirmBatch] = useState(false);
  const [finalizingId, setFinalizingId] = useState<number | null>(null);

  // Завершённые (по умолчанию) | Черновики (active) | Все
  const [view, setView] = useState<'finished' | 'drafts' | 'all'>('finished');

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

  const selMode = selected.size > 0;

  return (
    <div className="history-container" style={styles.container}>
      {/* Top bar */}
      <div style={styles.topBar}>
        <button onClick={onBack} className="t-btn" style={styles.backBtn}>&larr; К переговорам</button>
        <span style={styles.topTitle}>ИСТОРИЯ ВСТРЕЧ</span>
        <span style={styles.topMeta}>{meetings.length} встреч</span>
      </div>

      {/* Header */}
      <div style={styles.headerRow}>
        <div>
          <h2 style={styles.title}>
            Архив<span style={{ color: theme.accent.amber }}> встреч</span>
          </h2>
          <div style={styles.subtitle}>Сохраненные встречи с транскрипцией и подсказками</div>
        </div>

        {/* Batch controls */}
        {meetings.length > 0 && (
          <div style={styles.batchBar}>
            <button onClick={toggleAll} className="t-btn" style={styles.selectAllBtn}>
              {selected.size === meetings.length ? 'Снять все' : 'Выбрать все'}
            </button>
            {selMode && !confirmBatch && (
              <button onClick={() => setConfirmBatch(true)} className="t-btn t-btn-red" style={styles.batchDeleteBtn}>
                Удалить ({selected.size})
              </button>
            )}
            {selMode && confirmBatch && (
              <>
                <span style={{ color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 }}>
                  Удалить {selected.size} встреч?
                </span>
                <button onClick={handleBatchDelete} disabled={deleting} className="t-btn t-btn-red" style={styles.confirmYes}>
                  {deleting ? '...' : 'Да'}
                </button>
                <button onClick={() => setConfirmBatch(false)} className="t-btn" style={styles.confirmNo}>Отмена</button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Вид: завершённые / черновики / все */}
      <div style={styles.viewTabs}>
        {([['finished', 'Завершённые'], ['drafts', 'Черновики'], ['all', 'Все']] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className="t-btn"
            style={view === key ? styles.viewTabActive : styles.viewTab}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Фильтры (Этап 1 MVP) */}
      <div style={styles.filters}>
        <Select
          style={styles.filterSelect}
          ariaLabel="Фильтр по заказчику"
          value={String(filterCustomerId)}
          onChange={(v) => onCustomerChange(v === '' ? '' : Number(v))}
          options={[{ value: '', label: 'Все заказчики' },
            ...customers.map((c) => ({ value: String(c.id), label: c.name }))]}
        />
        <Select
          style={styles.filterSelect}
          ariaLabel="Фильтр по объекту"
          value={String(filterObjectId)}
          onChange={(v) => setFilterObjectId(v === '' ? '' : Number(v))}
          options={[{ value: '', label: 'Все объекты' },
            ...objects.map((o) => ({ value: String(o.id), label: o.name }))]}
        />
        <input
          style={styles.filterInput}
          placeholder="Поиск по названию/теме…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') applySearch(); }}
        />
        <button className="t-btn t-btn-amber" style={styles.filterBtn} onClick={applySearch}>Найти</button>
      </div>

      {/* Content */}
      {loading && <div style={styles.empty}>Загрузка...</div>}
      {error && <div style={{ ...styles.empty, color: theme.accent.red }}>{error}</div>}

      {!loading && !error && meetings.length === 0 && (
        <div style={styles.emptyCard}>
          <div style={styles.emptyIcon}>&#9711;</div>
          <div style={styles.emptyText}>
            {view === 'drafts' ? 'Нет черновиков' : view === 'all' ? 'Нет встреч' : 'Нет завершённых встреч'}
          </div>
          <div style={styles.emptyHint}>
            {view === 'finished' ? 'Встречи появятся здесь после завершения сессии' : 'Незавершённые встречи (запись с устройства/ПК) показываются здесь'}
          </div>
        </div>
      )}

      {!loading && meetings.length > 0 && (
        <div style={styles.list}>
          {meetings.map((m) => (
            <div key={m.id} style={{ display: 'flex', alignItems: 'stretch', gap: 0 }}>
              {/* Checkbox */}
              <label
                style={{
                  ...styles.checkWrap,
                  borderColor: selected.has(m.id) ? theme.accent.amber : 'rgba(255,255,255,0.06)',
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <input
                  type="checkbox"
                  checked={selected.has(m.id)}
                  onChange={() => toggleSelect(m.id)}
                  style={{ display: 'none' }}
                />
                <span style={{
                  ...styles.checkbox,
                  background: selected.has(m.id) ? theme.accent.amber : 'transparent',
                  borderColor: selected.has(m.id) ? theme.accent.amber : theme.text.muted,
                }}>
                  {selected.has(m.id) && <span style={styles.checkmark}>&#10003;</span>}
                </span>
              </label>
              {/* Card */}
              <button
                style={{
                  ...styles.card,
                  borderTopLeftRadius: 0,
                  borderBottomLeftRadius: 0,
                  borderLeft: 'none',
                  borderColor: selected.has(m.id) ? 'rgba(245,166,35,0.3)' : undefined,
                }}
                {...navTo(paths.meetingDetail(m.id), () => onSelectMeeting(m.id))}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.borderColor = 'rgba(245,166,35,0.3)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.borderColor = selected.has(m.id) ? 'rgba(245,166,35,0.3)' : 'rgba(255,255,255,0.06)';
                }}
              >
                <div style={styles.cardTop}>
                  <div style={styles.cardTitle}>{meetingDisplayName(m)}</div>
                  <div style={styles.cardDate}>
                    {formatDate(m.started_at)} &middot; {formatTime(m.started_at)}
                  </div>
                </div>

                {m.meeting_topic && (
                  <div style={styles.cardTopic}>{m.meeting_topic}</div>
                )}

                {(m.customer_name || m.object_name) && (
                  <div style={styles.cardDir}>
                    {m.customer_name && <span style={styles.dirChip}>🏢 {m.customer_name}</span>}
                    {m.object_name && <span style={styles.dirChip}>📍 {m.object_name}</span>}
                  </div>
                )}

                {m.micro_summary && <div style={styles.cardTopic}>{m.micro_summary}</div>}

                {m.tags && m.tags.length > 0 && (
                  <div style={styles.cardDir}>
                    {m.tags.map((t) => <span key={t} style={styles.tagChip}>#{t}</span>)}
                  </div>
                )}

                <div style={styles.cardBadges}>
                  {m.finalization_status && m.finalization_status !== 'not_started' && (
                    <span style={finBadgeStyle(m.finalization_status)}>{FIN_LABELS[m.finalization_status] || m.finalization_status}</span>
                  )}
                  {m.negotiation_type && (
                    <span style={styles.badge}>
                      {NEGOTIATION_TYPE_LABELS[m.negotiation_type] || m.negotiation_type}
                    </span>
                  )}
                  <span style={styles.badgeBlue}>
                    {m.segment_count} сегм.
                  </span>
                  <span style={styles.badgeGreen}>
                    {m.suggestion_count} подск.
                  </span>
                  <span style={styles.badgeMuted}>
                    {formatDuration(m.recorded_seconds)}
                  </span>
                </div>
              </button>
              {m.status === 'active' && (
                <button
                  className="t-btn t-btn-green"
                  style={styles.finalizeSide}
                  onClick={() => handleFinalize(m.id)}
                  disabled={finalizingId === m.id}
                  title="Завершить встречу"
                >
                  {finalizingId === m.id ? '…' : '✓'}
                </button>
              )}
              {m.finalization_status === 'error' && (
                <button className="t-btn t-btn-red" style={styles.retrySide} onClick={() => handleRetry(m.id)} title="Повторить формирование протокола">↻</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '28px 32px',
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
    overflow: 'auto',
    flex: 1,
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    paddingBottom: 16,
    borderBottom: `1px solid ${theme.border.default}`,
  },
  backBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 16px',
    background: 'transparent',
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 6,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.04em',
    flexShrink: 0,
  },
  topTitle: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    fontWeight: 500,
    letterSpacing: '0.16em',
    color: theme.text.secondary,
    flex: 1,
  },
  topMeta: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
  },
  headerRow: {
    display: 'flex',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    gap: 16,
    flexWrap: 'wrap' as const,
  },
  title: {
    margin: 0,
    fontSize: 28,
    fontFamily: theme.font.heading,
    fontWeight: 800,
    color: theme.text.primary,
  },
  subtitle: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.text.muted,
    letterSpacing: '0.06em',
    marginTop: 4,
  },
  batchBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexShrink: 0,
  },
  selectAllBtn: {
    padding: '4px 12px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 5,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.04em',
  },
  batchDeleteBtn: {
    padding: '4px 12px',
    background: 'transparent',
    border: `1px solid ${theme.accent.red}`,
    borderRadius: 5,
    color: theme.accent.red,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.04em',
  },
  confirmYes: {
    padding: '4px 12px',
    background: theme.accent.red,
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 600,
  },
  confirmNo: {
    padding: '4px 12px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 4,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
  },
  empty: {
    textAlign: 'center',
    padding: 40,
    color: theme.text.secondary,
    fontFamily: theme.font.mono,
    fontSize: 13,
  },
  emptyCard: {
    textAlign: 'center',
    padding: '60px 20px',
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
  },
  emptyIcon: {
    fontSize: 48,
    color: theme.text.muted,
    marginBottom: 16,
  },
  emptyText: {
    fontFamily: theme.font.heading,
    fontSize: 16,
    fontWeight: 700,
    color: theme.text.secondary,
    marginBottom: 8,
  },
  emptyHint: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.text.muted,
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  checkWrap: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 40,
    flexShrink: 0,
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRight: 'none',
    borderRadius: '10px 0 0 10px',
    cursor: 'pointer',
  },
  checkbox: {
    width: 16,
    height: 16,
    borderRadius: 3,
    border: '1.5px solid',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.15s',
  },
  checkmark: {
    fontSize: 10,
    color: '#080A0F',
    fontWeight: 700,
    lineHeight: 1,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    padding: '16px 20px',
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: '0 10px 10px 0',
    cursor: 'pointer',
    textAlign: 'left',
    flex: 1,
    minWidth: 0,
    transition: 'border-color 0.15s',
    color: theme.text.primary,
    fontFamily: theme.font.body,
  },
  cardTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  cardTitle: {
    fontFamily: theme.font.body,
    fontWeight: 700,
    fontSize: 15,
    color: theme.text.primary,
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  cardDate: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
    flexShrink: 0,
  },
  cardTopic: {
    fontFamily: theme.font.body,
    fontSize: 12,
    color: theme.text.secondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  cardDir: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap' as const,
  },
  dirChip: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.secondary,
    background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 4,
    padding: '2px 8px',
  },
  tagChip: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.accent.amber,
    background: theme.accent.amberGlow,
    border: '1px solid rgba(245,166,35,0.2)',
    borderRadius: 4,
    padding: '2px 8px',
  },
  retrySide: {
    flexShrink: 0,
    width: 40,
    background: theme.bg.card,
    border: `1px solid ${theme.accent.red}`,
    borderLeft: 'none',
    borderRadius: '0 10px 10px 0',
    color: theme.accent.red,
    cursor: 'pointer',
    fontSize: 16,
  },
  finalizeSide: {
    flexShrink: 0,
    width: 40,
    background: theme.bg.card,
    border: `1px solid ${theme.accent.green}`,
    borderLeft: 'none',
    borderRadius: '0 10px 10px 0',
    color: theme.accent.green,
    cursor: 'pointer',
    fontSize: 16,
  },
  viewTabs: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap' as const,
  },
  viewTab: {
    padding: '6px 14px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 20,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.mono,
    letterSpacing: '0.04em',
  },
  viewTabActive: {
    padding: '6px 14px',
    background: theme.accent.amberGlow,
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 20,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.04em',
  },
  filters: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap' as const,
    alignItems: 'center',
  },
  filterSelect: {
    padding: '8px 12px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 12,
    fontFamily: theme.font.body,
    outline: 'none',
  },
  filterInput: {
    padding: '8px 12px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 12,
    fontFamily: theme.font.body,
    outline: 'none',
    flex: 1,
    minWidth: 160,
  },
  filterBtn: {
    padding: '8px 16px',
    background: 'transparent',
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 7,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.04em',
  },
  cardBadges: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
  },
  badge: {
    padding: '2px 8px',
    background: theme.accent.amberGlow,
    border: '1px solid rgba(245,166,35,0.2)',
    borderRadius: 4,
    fontFamily: theme.font.mono,
    fontSize: 9,
    fontWeight: 600,
    color: theme.accent.amber,
    letterSpacing: '0.06em',
    textTransform: 'uppercase' as const,
  },
  badgeBlue: {
    padding: '2px 8px',
    background: 'rgba(91,156,246,0.1)',
    border: '1px solid rgba(91,156,246,0.2)',
    borderRadius: 4,
    fontFamily: theme.font.mono,
    fontSize: 9,
    fontWeight: 600,
    color: theme.accent.blue,
    letterSpacing: '0.04em',
  },
  badgeGreen: {
    padding: '2px 8px',
    background: theme.accent.greenDim,
    border: '1px solid rgba(46,229,157,0.2)',
    borderRadius: 4,
    fontFamily: theme.font.mono,
    fontSize: 9,
    fontWeight: 600,
    color: theme.accent.green,
    letterSpacing: '0.04em',
  },
  badgeMuted: {
    padding: '2px 8px',
    background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 4,
    fontFamily: theme.font.mono,
    fontSize: 9,
    color: theme.text.muted,
    letterSpacing: '0.04em',
  },
};
