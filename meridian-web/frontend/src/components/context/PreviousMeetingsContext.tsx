import { useState, useEffect, useCallback, useRef } from 'react';
import { theme } from '../../styles/theme';
import { apiErrorMessage } from '../../lib/apiError';
import {
  listContextCandidates, listContextSources, addContextSource,
  updateContextSource, deleteContextSource,
} from '../../api/meetingContextSources';
import type { MeetingContextSource, PreviousMeetingCandidate } from '../../types';
import { ContextSourceCard } from './ContextSourceCard';
import {
  previousMeetingSourceToContextSourceViewModel,
  previousMeetingCandidateToContextSourceViewModel,
  type ContextSourceSectionSummary,
} from './contextSourceModel';

interface Props {
  meetingId: number;
  readOnly?: boolean;
  currentCustomerId?: number | null;
  currentObjectId?: number | null;
  onSummaryChange?: (summary: ContextSourceSectionSummary) => void;
}

type Filter = 'all' | 'customer' | 'object';

export function PreviousMeetingsContext({ meetingId, readOnly, currentCustomerId, currentObjectId, onSummaryChange }: Props) {
  const [sources, setSources] = useState<MeetingContextSource[]>([]);
  const [candidates, setCandidates] = useState<PreviousMeetingCandidate[]>([]);
  const [filter, setFilter] = useState<Filter>(currentObjectId ? 'object' : currentCustomerId ? 'customer' : 'all');
  const [q, setQ] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const prevSources = sources.filter((s) => s.source_type === 'previous_meeting');

  const loadSources = useCallback(async () => {
    try { setSources(await listContextSources(meetingId)); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось загрузить контекст')); }
  }, [meetingId]);

  const loadCandidates = useCallback(async () => {
    try {
      setCandidates(await listContextCandidates(meetingId, {
        q: q || undefined,
        customer_id: filter === 'customer' && currentCustomerId != null ? currentCustomerId : undefined,
        object_id: filter === 'object' && currentObjectId != null ? currentObjectId : undefined,
      }));
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось загрузить кандидатов')); }
  }, [meetingId, q, filter, currentCustomerId, currentObjectId]);

  useEffect(() => { loadSources(); }, [loadSources]);
  useEffect(() => { if (showAdd && !readOnly) loadCandidates(); }, [showAdd, readOnly, loadCandidates]);

  // Сводка для корзины (только выбранные прошлые встречи). Колбэк в ref → effect
  // зависит лишь от sources, без render-loop.
  const onSummaryChangeRef = useRef(onSummaryChange);
  onSummaryChangeRef.current = onSummaryChange;
  useEffect(() => {
    if (!onSummaryChangeRef.current) return;
    const ps = sources.filter((s) => s.source_type === 'previous_meeting');
    onSummaryChangeRef.current({ total: ps.length, included: ps.filter((s) => s.included).length });
  }, [sources]);

  async function add(c: PreviousMeetingCandidate) {
    setError(null);
    try {
      await addContextSource(meetingId, { source_type: 'previous_meeting', source_id: c.meeting_id, included: true });
      await loadSources(); await loadCandidates();
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось добавить встречу')); }
  }

  async function toggle(s: MeetingContextSource) {
    setError(null);
    try {
      const u = await updateContextSource(meetingId, s.id, { included: !s.included });
      setSources((xs) => xs.map((x) => (x.id === s.id ? u : x)));
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось обновить')); }
  }

  async function setPriority(s: MeetingContextSource, priority: number) {
    try {
      const u = await updateContextSource(meetingId, s.id, { priority });
      setSources((xs) => xs.map((x) => (x.id === s.id ? u : x)));
    } catch { /* ignore */ }
  }

  async function remove(s: MeetingContextSource) {
    setError(null);
    try {
      await deleteContextSource(meetingId, s.id);
      setSources((xs) => xs.filter((x) => x.id !== s.id));
      await loadCandidates();
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось удалить')); }
  }

  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>Предыдущие встречи как контекст</span>
        <span style={{ flex: 1 }} />
        {!readOnly && (
          <button style={styles.addToggle} onClick={() => setShowAdd((v) => !v)}>
            {showAdd ? 'Скрыть' : '+ Добавить'}
          </button>
        )}
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {/* выбранные источники */}
      {prevSources.length === 0 ? (
        <div style={styles.muted}>Прошлые встречи не выбраны. Итоги выбранных встреч попадут в подсказки.</div>
      ) : (
        <div style={styles.list}>
          {prevSources.map((s) => (
            <ContextSourceCard
              key={s.id}
              source={previousMeetingSourceToContextSourceViewModel(s)}
              readOnly={readOnly}
              onToggleIncluded={readOnly ? undefined : () => toggle(s)}
              onPriorityChange={readOnly ? undefined : (p) => setPriority(s, p)}
              onRemove={readOnly ? undefined : () => remove(s)}
            />
          ))}
        </div>
      )}

      {/* добавление кандидатов */}
      {!readOnly && showAdd && (
        <div style={styles.addBox}>
          <div style={styles.filters}>
            <input
              style={styles.search} placeholder="Поиск по названию/итогу…"
              value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadCandidates()}
            />
            {(['all', 'customer', 'object'] as Filter[]).map((f) => {
              const disabled = (f === 'customer' && currentCustomerId == null) || (f === 'object' && currentObjectId == null);
              return (
                <button key={f} disabled={disabled}
                  style={filter === f ? styles.filterOn : styles.filterOff}
                  onClick={() => setFilter(f)}>
                  {f === 'all' ? 'Все доступные' : f === 'customer' ? 'Тот же заказчик' : 'Тот же объект'}
                </button>
              );
            })}
          </div>
          {candidates.length === 0 ? (
            <div style={styles.muted}>Нет подходящих завершённых встреч.</div>
          ) : (
            <div style={styles.list}>
              {candidates.map((c) => (
                <ContextSourceCard
                  key={c.meeting_id}
                  source={previousMeetingCandidateToContextSourceViewModel(c)}
                  compact
                  right={c.already_added ? <span style={styles.badgeOn}>добавлена</span> : undefined}
                  onPrimaryAction={c.already_added ? undefined : () => add(c)}
                  primaryActionLabel={c.already_added ? undefined : 'Добавить'}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: { background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 20, display: 'flex', flexDirection: 'column', gap: 10 },
  header: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  title: { fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: theme.text.primary },
  addToggle: { padding: '5px 12px', background: theme.accent.amberGlow, border: `1px solid ${theme.accent.amber}`, borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono },
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  srcRow: { display: 'flex', alignItems: 'center', gap: 10, padding: 10, background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, borderRadius: 8 },
  candRow: { display: 'flex', alignItems: 'center', gap: 10, padding: 10, background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 8 },
  srcTitle: { fontSize: 13, fontWeight: 600, color: theme.text.primary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const },
  srcSub: { fontSize: 12, color: theme.text.secondary, lineHeight: 1.4, marginTop: 2 },
  srcMeta: { fontSize: 10, fontFamily: theme.font.mono, color: theme.text.muted, marginTop: 3 },
  srcControls: { display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 },
  incl: { display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, fontFamily: theme.font.mono, color: theme.text.secondary },
  prio: { width: 50, padding: '4px 6px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 5, color: theme.text.primary, fontSize: 11, fontFamily: theme.font.mono },
  remove: { padding: '4px 9px', background: 'transparent', border: `1px solid ${theme.accent.red}`, borderRadius: 5, color: theme.accent.red, cursor: 'pointer', fontSize: 11 },
  addBox: { display: 'flex', flexDirection: 'column', gap: 10, marginTop: 6, paddingTop: 10, borderTop: `1px solid ${theme.border.default}` },
  filters: { display: 'flex', gap: 6, flexWrap: 'wrap' as const },
  search: { flex: 1, minWidth: 160, padding: '7px 10px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.primary, fontSize: 12, fontFamily: theme.font.body, outline: 'none' },
  filterOn: { padding: '6px 10px', background: theme.accent.amberGlow, border: `1px solid ${theme.accent.amber}`, borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono },
  filterOff: { padding: '6px 10px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.secondary, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono },
  addBtn: { padding: '6px 12px', background: theme.accent.green, border: 'none', borderRadius: 6, color: '#080A0F', cursor: 'pointer', fontSize: 11, fontWeight: 600, fontFamily: theme.font.body, flexShrink: 0 },
  badgeOn: { padding: '3px 9px', border: `1px solid ${theme.accent.green}`, borderRadius: 10, fontFamily: theme.font.mono, fontSize: 9, color: theme.accent.green, flexShrink: 0 },
  badgeOff: { padding: '3px 9px', border: `1px solid ${theme.border.default}`, borderRadius: 10, fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted, flexShrink: 0 },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 12 },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
};
