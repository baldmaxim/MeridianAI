import { useState } from 'react';
import { apiErrorMessage } from '../../lib/apiError';
import { useCandidates, useApproveCandidate, useRejectCandidate, usePatchCandidate } from '../../hooks/queries/learning';
import type { LearningCandidate, LearningCandidateType } from '../../types';
import styles from './LearningCandidates.module.css';
import { cx } from '../../utils/cx';
import { TextInput } from '../common';

interface Props {
  meetingId?: number | null;   // если задан — только кандидаты этой встречи
  onChange?: () => void;       // после approve/reject (для обновления счётчиков)
  compact?: boolean;           // компактный вид (в панели итогов)
}

const TYPE_LABEL: Record<LearningCandidateType, string> = {
  term: 'Термин',
  trigger_phrase: 'Триггер',
  playbook: 'Playbook',
  counterparty_trait: 'Особенность',
  forbidden_phrase: 'Не говорить',
};

const TYPE_TONES: Record<LearningCandidateType, string> = {
  term: styles.toneBlue,
  trigger_phrase: styles.toneAmber,
  playbook: styles.toneGreen,
  counterparty_trait: styles.toneAmber,
  forbidden_phrase: styles.toneRed,
};

// Поля для редактирования по типу: [ключ payload, подпись, многострочное?]
const EDIT_FIELDS: Record<LearningCandidateType, Array<[string, string, boolean]>> = {
  term: [['term', 'Термин', false], ['definition', 'Определение', true]],
  trigger_phrase: [['phrase', 'Фраза-триггер', false], ['recommended_reaction', 'Реакция', true]],
  playbook: [['situation', 'Ситуация', true], ['recommended_phrase', 'Что сказать', true]],
  counterparty_trait: [['trait', 'Особенность', true], ['recommended_strategy', 'Стратегия', true]],
  forbidden_phrase: [['phrase_or_risk', 'Чего избегать', true], ['better_alternative', 'Лучше сказать', true]],
};

function summary(c: LearningCandidate): string {
  const p = c.payload as Record<string, string>;
  switch (c.candidate_type) {
    case 'term': return `${p.term || ''} — ${p.definition || ''}`;
    case 'trigger_phrase': return `«${p.phrase || ''}» → ${p.recommended_reaction || ''}`;
    case 'playbook': return `${p.situation || ''} → «${p.recommended_phrase || ''}»`;
    case 'counterparty_trait': return `${p.trait || ''}${p.recommended_strategy ? ' → ' + p.recommended_strategy : ''}`;
    case 'forbidden_phrase': return `${p.phrase_or_risk || ''}${p.better_alternative ? ' → лучше: ' + p.better_alternative : ''}`;
    default: return c.title;
  }
}

export function LearningCandidates({ meetingId, onChange, compact }: Props) {
  const { data, isPending, error: queryError } = useCandidates(meetingId);
  const items = data ?? [];
  const approveMut = useApproveCandidate();
  const rejectMut = useRejectCandidate();
  const patchMut = usePatchCandidate();

  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});

  async function act(id: number, runner: (id: number) => Promise<unknown>) {
    setBusyId(id); setActionError(null);
    try {
      await runner(id);
      onChange?.();
    } catch (e) { setActionError(apiErrorMessage(e, 'Действие не выполнено')); }
    finally { setBusyId(null); }
  }

  function startEdit(c: LearningCandidate) {
    const p = c.payload as Record<string, string>;
    const d: Record<string, string> = { __title: c.title };
    for (const [key] of EDIT_FIELDS[c.candidate_type]) d[key] = (p[key] as string) || '';
    setDraft(d); setEditId(c.id);
  }

  async function saveEdit(c: LearningCandidate) {
    setBusyId(c.id); setActionError(null);
    try {
      const payload = { ...c.payload };
      for (const [key] of EDIT_FIELDS[c.candidate_type]) payload[key] = draft[key] ?? '';
      await patchMut.mutateAsync({ id: c.id, patch: { title: draft.__title, payload } });
      setEditId(null);
    } catch (e) { setActionError(apiErrorMessage(e, 'Не удалось сохранить')); }
    finally { setBusyId(null); }
  }

  if (isPending) return <div className={styles.muted}>Загрузка кандидатов…</div>;
  const error = actionError ?? (queryError ? apiErrorMessage(queryError, 'Не удалось загрузить кандидатов') : null);
  if (error) return <div className={styles.error}>{error}</div>;
  if (items.length === 0) {
    return <div className={styles.muted}>{meetingId != null ? 'Новых элементов не предложено' : 'Нет кандидатов на проверку'}</div>;
  }

  return (
    <div className={styles.list}>
      {items.map((c) => (
        <div key={c.id} className={styles.card}>
          <div className={styles.row}>
            <span className={cx(styles.badge, TYPE_TONES[c.candidate_type])}>
              {TYPE_LABEL[c.candidate_type]}
            </span>
            {c.confidence != null && <span className={styles.conf}>{Math.round(c.confidence * 100)}%</span>}
            <span className={styles.spacer} />
          </div>

          {editId === c.id ? (
            <div className={styles.editBox}>
              <label className={styles.lbl}>Заголовок</label>
              <TextInput inputClassName={styles.input} value={draft.__title || ''} onChange={(e) => setDraft({ ...draft, __title: e.target.value })} onClear={() => setDraft({ ...draft, __title: '' })} clearLabel="заголовок" />
              {EDIT_FIELDS[c.candidate_type].map(([key, label, multi]) => (
                <div key={key}>
                  <label className={styles.lbl}>{label}</label>
                  {multi ? (
                    <textarea className={styles.textarea} rows={2} value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
                  ) : (
                    <TextInput inputClassName={styles.input} value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} onClear={() => setDraft({ ...draft, [key]: '' })} clearLabel={label} />
                  )}
                </div>
              ))}
              <div className={styles.actions}>
                <button className={styles.approve} disabled={busyId === c.id} onClick={() => saveEdit(c)}>Сохранить</button>
                <button className={styles.ghost} disabled={busyId === c.id} onClick={() => setEditId(null)}>Отмена</button>
              </div>
            </div>
          ) : (
            <>
              <div className={styles.title}>{c.title}</div>
              {!compact && <div className={styles.summary}>{summary(c)}</div>}
              {c.source_text && <div className={styles.source}>«{c.source_text}»</div>}
            </>
          )}

          {editId !== c.id && (
            <div className={styles.actions}>
              <button className={styles.approve} disabled={busyId === c.id} onClick={() => act(c.id, (id) => approveMut.mutateAsync(id))}>В базу знаний</button>
              <button className={styles.reject} disabled={busyId === c.id} onClick={() => act(c.id, (id) => rejectMut.mutateAsync(id))}>Отклонить</button>
              <button className={styles.ghost} disabled={busyId === c.id} onClick={() => startEdit(c)}>Изменить</button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
