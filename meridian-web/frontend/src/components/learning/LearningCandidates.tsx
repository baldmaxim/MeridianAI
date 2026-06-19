import { useState } from 'react';
import { theme } from '../../styles/theme';
import { apiErrorMessage } from '../../lib/apiError';
import { useCandidates, useApproveCandidate, useRejectCandidate, usePatchCandidate } from '../../hooks/queries/learning';
import type { LearningCandidate, LearningCandidateType } from '../../types';

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

const TYPE_COLOR: Record<LearningCandidateType, string> = {
  term: theme.accent.blue,
  trigger_phrase: theme.accent.amber,
  playbook: theme.accent.green,
  counterparty_trait: theme.accent.amber,
  forbidden_phrase: theme.accent.red,
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

  if (isPending) return <div style={styles.muted}>Загрузка кандидатов…</div>;
  const error = actionError ?? (queryError ? apiErrorMessage(queryError, 'Не удалось загрузить кандидатов') : null);
  if (error) return <div style={styles.error}>{error}</div>;
  if (items.length === 0) {
    return <div style={styles.muted}>{meetingId != null ? 'Новых элементов не предложено' : 'Нет кандидатов на проверку'}</div>;
  }

  return (
    <div style={styles.list}>
      {items.map((c) => (
        <div key={c.id} style={styles.card}>
          <div style={styles.row}>
            <span style={{ ...styles.badge, color: TYPE_COLOR[c.candidate_type], borderColor: TYPE_COLOR[c.candidate_type] }}>
              {TYPE_LABEL[c.candidate_type]}
            </span>
            {c.confidence != null && <span style={styles.conf}>{Math.round(c.confidence * 100)}%</span>}
            <span style={{ flex: 1 }} />
          </div>

          {editId === c.id ? (
            <div style={styles.editBox}>
              <label style={styles.lbl}>Заголовок</label>
              <input style={styles.input} value={draft.__title || ''} onChange={(e) => setDraft({ ...draft, __title: e.target.value })} />
              {EDIT_FIELDS[c.candidate_type].map(([key, label, multi]) => (
                <div key={key}>
                  <label style={styles.lbl}>{label}</label>
                  {multi ? (
                    <textarea style={styles.textarea} rows={2} value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
                  ) : (
                    <input style={styles.input} value={draft[key] || ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
                  )}
                </div>
              ))}
              <div style={styles.actions}>
                <button style={styles.approve} disabled={busyId === c.id} onClick={() => saveEdit(c)}>Сохранить</button>
                <button style={styles.ghost} disabled={busyId === c.id} onClick={() => setEditId(null)}>Отмена</button>
              </div>
            </div>
          ) : (
            <>
              <div style={styles.title}>{c.title}</div>
              {!compact && <div style={styles.summary}>{summary(c)}</div>}
              {c.source_text && <div style={styles.source}>«{c.source_text}»</div>}
            </>
          )}

          {editId !== c.id && (
            <div style={styles.actions}>
              <button style={styles.approve} disabled={busyId === c.id} onClick={() => act(c.id, (id) => approveMut.mutateAsync(id))}>В базу знаний</button>
              <button style={styles.reject} disabled={busyId === c.id} onClick={() => act(c.id, (id) => rejectMut.mutateAsync(id))}>Отклонить</button>
              <button style={styles.ghost} disabled={busyId === c.id} onClick={() => startEdit(c)}>Изменить</button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  list: { display: 'flex', flexDirection: 'column', gap: 10 },
  card: { background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, borderRadius: 9, padding: 12, display: 'flex', flexDirection: 'column', gap: 7 },
  row: { display: 'flex', alignItems: 'center', gap: 8 },
  badge: { padding: '2px 9px', border: '1px solid', borderRadius: 10, fontFamily: theme.font.mono, fontSize: 9, letterSpacing: '0.06em', textTransform: 'uppercase' as const },
  conf: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  title: { fontSize: 13, fontWeight: 600, color: theme.text.primary },
  summary: { fontSize: 12, color: theme.text.secondary, lineHeight: 1.4 },
  source: { fontSize: 11, color: theme.text.muted, fontStyle: 'italic' as const, borderLeft: `2px solid ${theme.border.amber}`, paddingLeft: 8 },
  actions: { display: 'flex', gap: 8, flexWrap: 'wrap' as const, marginTop: 2 },
  approve: { padding: '6px 12px', background: theme.accent.green, border: 'none', borderRadius: 6, color: '#080A0F', cursor: 'pointer', fontSize: 11, fontWeight: 600, fontFamily: theme.font.body },
  reject: { padding: '6px 12px', background: 'transparent', border: `1px solid ${theme.accent.red}`, borderRadius: 6, color: theme.accent.red, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono },
  ghost: { padding: '6px 12px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.secondary, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono },
  editBox: { display: 'flex', flexDirection: 'column', gap: 4 },
  lbl: { fontSize: 9, fontFamily: theme.font.mono, color: theme.accent.amber, letterSpacing: '0.08em', textTransform: 'uppercase' as const, marginTop: 4 },
  input: { padding: '7px 10px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.primary, fontSize: 12, fontFamily: theme.font.body, outline: 'none', width: '100%', boxSizing: 'border-box' as const },
  textarea: { padding: '7px 10px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.primary, fontSize: 12, fontFamily: theme.font.body, outline: 'none', resize: 'vertical' as const, width: '100%', boxSizing: 'border-box' as const },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 12 },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
};
