import { useState, useEffect, useCallback, useRef } from 'react';
import { apiErrorMessage } from '../../lib/apiError';
import { useMeetingStore } from '../../store/meetingStore';
import {
  listContextCandidates, listContextSources, addContextSource,
  updateContextSource, deleteContextSource,
} from '../../api/meetingContextSources';
import type { MeetingContextSource, PreviousMeetingCandidate } from '../../types';
import { ContextSourceCard } from './ContextSourceCard';
import { Modal } from '../common/Modal';
import { TextInput } from '../common';
import styles from './PreviousMeetingsContext.module.css';
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
  const scopeKind: 'object' | 'customer' | null =
    currentObjectId != null ? 'object' : currentCustomerId != null ? 'customer' : null;
  const scope: { kind: 'object' | 'customer'; name: string | null } | null =
    scopeKind === 'object' ? { kind: 'object', name: objectName }
    : scopeKind === 'customer' ? { kind: 'customer', name: customerName }
    : null;

  const prevSources = sources.filter((s) => s.source_type === 'previous_meeting');

  const loadSources = useCallback(async () => {
    try { setSources(await listContextSources(meetingId)); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось загрузить контекст')); }
  }, [meetingId]);

  const loadCandidates = useCallback(async () => {
    if (!scopeKind) { setCandidates([]); return; }
    try {
      setCandidates(await listContextCandidates(meetingId, {
        q: q || undefined,
        object_id: scopeKind === 'object' ? currentObjectId ?? undefined : undefined,
        customer_id: scopeKind === 'customer' ? currentCustomerId ?? undefined : undefined,
      }));
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось загрузить кандидатов')); }
  }, [meetingId, q, scopeKind, currentCustomerId, currentObjectId]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- setState внутри loadSources только после await (асинхронно)
  useEffect(() => { loadSources(); }, [loadSources]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- setState внутри loadCandidates: сброс без скоупа либо после await
  useEffect(() => { if (showAdd && !readOnly) loadCandidates(); }, [showAdd, readOnly, loadCandidates]);

  // Сводка для корзины (только выбранные прошлые встречи). Колбэк в ref → effect
  // зависит лишь от sources, без render-loop.
  const onSummaryChangeRef = useRef(onSummaryChange);
  useEffect(() => { onSummaryChangeRef.current = onSummaryChange; });
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
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>Предыдущие встречи как контекст</span>
        <span className={styles.spacer} />
        {!readOnly && (
          <button className={styles.addToggle} onClick={() => setShowAdd(true)}>
            + Добавить
          </button>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {/* выбранные источники */}
      {prevSources.length === 0 ? (
        <div className={styles.muted}>Прошлые встречи не выбраны. Итоги выбранных встреч попадут в подсказки.</div>
      ) : (
        <div className={styles.list}>
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
        <div className={styles.modalHead}>
          <span className={styles.title}>Добавить прошлую встречу</span>
          <span className={styles.spacer} />
          <button className={styles.modalClose} onClick={() => setShowAdd(false)} aria-label="Закрыть">×</button>
        </div>

        {scope ? (
          <div className={styles.scopeRow}>
            <span className={styles.scopeLabel}>{scope.kind === 'object' ? 'Объект' : 'Заказчик'}</span>
            <span className={styles.scopeName}>{scope.name || (scope.kind === 'object' ? 'текущий объект' : 'текущий заказчик')}</span>
          </div>
        ) : (
          <div className={styles.muted}>Выберите заказчика или объект, чтобы подобрать прошлые встречи.</div>
        )}

        {scope && (
          <>
            <TextInput
              inputClassName={styles.search} placeholder="Поиск по названию/итогу…"
              clearLabel="поиск" onClear={() => setQ('')}
              value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadCandidates()}
            />
            {candidates.length === 0 ? (
              <div className={styles.muted}>Нет подходящих завершённых встреч.</div>
            ) : (
              <div className={styles.list}>
                {candidates.map((c) => (
                  <ContextSourceCard
                    key={c.meeting_id}
                    source={previousMeetingCandidateToContextSourceViewModel(c)}
                    compact
                    right={c.already_added ? <span className={styles.badgeOn}>добавлена</span> : undefined}
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
