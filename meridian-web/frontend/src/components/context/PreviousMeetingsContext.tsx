import { useState, useEffect, useCallback, useRef } from 'react';
import { theme } from '../../styles/theme';
import { apiErrorMessage } from '../../lib/apiError';
import { useMeetingStore } from '../../store/meetingStore';
import {
  listContextCandidates, listContextSources, addContextSource,
  updateContextSource, deleteContextSource,
} from '../../api/meetingContextSources';
import type { MeetingContextSource, PreviousMeetingCandidate } from '../../types';
import { ContextSourceCard } from './ContextSourceCard';
import { Modal } from '../common/Modal';
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

export function PreviousMeetingsContext({ meetingId, readOnly, currentCustomerId, currentObjectId, onSummaryChange }: Props) {
  const [sources, setSources] = useState<MeetingContextSource[]>([]);
  const [candidates, setCandidates] = useState<PreviousMeetingCandidate[]>([]);
  const [q, setQ] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Имена для подписи скоупа (текущий объект/заказчик встречи).
  const objectName = useMeetingStore((s) => s.selectedObjectName);
  const customerName = useMeetingStore((s) => s.selectedCustomerName);

  // Строгий скоуп: текущий объект (если задан), иначе текущий заказчик.
  const scope: { kind: 'object' | 'customer'; name: string | null } | null =
    currentObjectId != null ? { kind: 'object', name: objectName }
    : currentCustomerId != null ? { kind: 'customer', name: customerName }
    : null;

  const prevSources = sources.filter((s) => s.source_type === 'previous_meeting');

  const loadSources = useCallback(async () => {
    try { setSources(await listContextSources(meetingId)); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось загрузить контекст')); }
  }, [meetingId]);

  const loadCandidates = useCallback(async () => {
    if (!scope) { setCandidates([]); return; }
    try {
      setCandidates(await listContextCandidates(meetingId, {
        q: q || undefined,
        object_id: scope.kind === 'object' ? currentObjectId ?? undefined : undefined,
        customer_id: scope.kind === 'customer' ? currentCustomerId ?? undefined : undefined,
      }));
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось загрузить кандидатов')); }
  }, [meetingId, q, scope, currentCustomerId, currentObjectId]);

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
          <button style={styles.addToggle} onClick={() => setShowAdd(true)}>
            + Добавить
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

      {/* модалка добавления — строго в рамках текущего объекта/заказчика */}
      <Modal open={!readOnly && showAdd} onClose={() => setShowAdd(false)} maxWidth={560}>
        <div style={styles.modalHead}>
          <span style={styles.title}>Добавить прошлую встречу</span>
          <span style={{ flex: 1 }} />
          <button style={styles.modalClose} onClick={() => setShowAdd(false)} aria-label="Закрыть">×</button>
        </div>

        {scope ? (
          <div style={styles.scopeRow}>
            <span style={styles.scopeLabel}>{scope.kind === 'object' ? 'Объект' : 'Заказчик'}</span>
            <span style={styles.scopeName}>{scope.name || (scope.kind === 'object' ? 'текущий объект' : 'текущий заказчик')}</span>
          </div>
        ) : (
          <div style={styles.muted}>Выберите заказчика или объект, чтобы подобрать прошлые встречи.</div>
        )}

        {scope && (
          <>
            <input
              style={styles.search} placeholder="Поиск по названию/итогу…"
              value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadCandidates()}
            />
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
          </>
        )}
      </Modal>
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
  modalHead: { display: 'flex', alignItems: 'center', gap: 8 },
  modalClose: { background: 'transparent', border: 'none', color: theme.text.secondary, cursor: 'pointer', fontSize: 22, lineHeight: 1, padding: 0, width: 28, height: 28 },
  scopeRow: { display: 'inline-flex', alignItems: 'baseline', gap: 8, padding: '6px 12px', borderRadius: 8, background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`, alignSelf: 'flex-start' },
  scopeLabel: { fontFamily: theme.font.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase' as const, color: theme.text.muted },
  scopeName: { fontFamily: theme.font.body, fontSize: 13, fontWeight: 600, color: theme.text.primary },
  search: { padding: '8px 12px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.primary, fontSize: 12, fontFamily: theme.font.body, outline: 'none' },
  badgeOn: { padding: '3px 9px', border: `1px solid ${theme.accent.green}`, borderRadius: 10, fontFamily: theme.font.mono, fontSize: 9, color: theme.accent.green, flexShrink: 0 },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 12 },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
};
