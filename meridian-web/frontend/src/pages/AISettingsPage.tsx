import { useState } from 'react';
import { theme } from '../styles/theme';
import { Select, Combobox } from '../components/common';
import { apiErrorMessage } from '../lib/apiError';
import {
  useProfiles, useAiOptions, useCreateProfile, useUpdateProfile, useDeleteProfile, useMakeDefaultProfile,
} from '../hooks/queries/aiSettings';
import type { AISettingsProfile, AISettingsProfileInput, SuggestionMode } from '../types';

interface Props { onBack: () => void; }

const MODES: { key: SuggestionMode; label: string; hint: string }[] = [
  { key: 'fast', label: 'Быстрый', hint: 'Меньше контекста, короче, ниже задержка' },
  { key: 'balanced', label: 'Сбалансированный', hint: 'Текущие дефолты' },
  { key: 'deep', label: 'Глубокий', hint: 'Больше контекста для manual/strengthen/финализации' },
];

const TOGGLES: { key: keyof AISettingsProfileInput; label: string }[] = [
  { key: 'auto_suggestions_enabled', label: 'Авто-подсказки' },
  { key: 'document_context_enabled', label: 'Контекст документов' },
  { key: 'knowledge_context_enabled', label: 'База знаний' },
  { key: 'previous_meetings_context_enabled', label: 'Прошлые встречи' },
  { key: 'suggestion_structured_enabled', label: 'Структурированные подсказки' },
  { key: 'finalization_enabled', label: 'Финализация (протокол)' },
  { key: 'learning_extraction_enabled', label: 'Авто-обучение базы знаний' },
  { key: 'conversation_tree_enabled', label: 'Дерево общения (live)' },
];

const MODEL_FIELDS: { key: keyof AISettingsProfileInput; label: string }[] = [
  { key: 'live_suggestion_model', label: 'Модель live-подсказок' },
  { key: 'strengthen_model', label: 'Модель усиления позиции' },
  { key: 'finalization_model', label: 'Модель финализации' },
  { key: 'learning_model', label: 'Модель авто-обучения' },
];

const LIMIT_FIELDS: { key: keyof AISettingsProfileInput; label: string }[] = [
  { key: 'max_auto_cards', label: 'Макс. авто-карточек' },
  { key: 'max_manual_cards', label: 'Макс. ручных карточек' },
  { key: 'auto_suggestion_min_interval_seconds', label: 'Интервал авто-подсказок, сек' },
  { key: 'document_context_max_chunks', label: 'Документы: макс. фрагментов' },
  { key: 'document_context_max_chars', label: 'Документы: макс. символов' },
  { key: 'previous_context_max_meetings', label: 'Прошлые встречи: макс. кол-во' },
  { key: 'previous_context_max_chars', label: 'Прошлые встречи: макс. символов' },
  { key: 'knowledge_context_max_items', label: 'База знаний: макс. элементов' },
];

function blankDraft(): AISettingsProfileInput {
  return {
    name: '', suggestion_mode: 'balanced',
    auto_suggestions_enabled: true, document_context_enabled: true, knowledge_context_enabled: true,
    previous_meetings_context_enabled: true, suggestion_structured_enabled: true,
    finalization_enabled: true, learning_extraction_enabled: true,
    conversation_tree_enabled: true,
  };
}

export function AISettingsPage({ onBack }: Props) {
  const [selectedId, setSelectedId] = useState<number | 'new' | null>(null);
  const [draft, setDraft] = useState<AISettingsProfileInput>(blankDraft());
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // profiles и options грузятся параллельно (нет водопада)
  const profilesRes = useProfiles();
  const { data: options = null } = useAiOptions();
  const profiles = profilesRes.data ?? [];

  const createMut = useCreateProfile();
  const updateMut = useUpdateProfile();
  const deleteMut = useDeleteProfile();
  const makeDefaultMut = useMakeDefaultProfile();
  const busy = createMut.isPending || updateMut.isPending || deleteMut.isPending || makeDefaultMut.isPending;

  // ошибка действий (error state) + ошибка загрузки профилей из query
  const displayError = error ?? (profilesRes.error ? apiErrorMessage(profilesRes.error, 'Не удалось загрузить профили') : null);

  function selectProfile(p: AISettingsProfile) {
    setSelectedId(p.id);
    setDraft({ ...p });
    setError(null); setInfo(null);
  }
  function startNew() {
    setSelectedId('new'); setDraft(blankDraft()); setError(null); setInfo(null);
  }
  function set<K extends keyof AISettingsProfileInput>(key: K, value: AISettingsProfileInput[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  async function save() {
    if (!draft.name?.trim()) { setError('Укажите название профиля'); return; }
    setError(null); setInfo(null);
    try {
      if (selectedId === 'new') {
        const p = await createMut.mutateAsync(draft);
        setInfo('Профиль создан'); selectProfile(p);
      } else if (typeof selectedId === 'number') {
        const p = await updateMut.mutateAsync({ id: selectedId, body: draft });
        setInfo('Сохранено'); setDraft({ ...p });
      }
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось сохранить профиль')); }
  }

  async function makeDefault(id: number) {
    setError(null);
    try { await makeDefaultMut.mutateAsync(id); setInfo('Профиль по умолчанию обновлён'); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось')); }
  }

  async function remove(id: number) {
    setError(null);
    try {
      await deleteMut.mutateAsync(id);
      if (selectedId === id) { setSelectedId(null); setDraft(blankDraft()); }
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось удалить (профиль по умолчанию удалить нельзя)')); }
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button onClick={onBack} style={styles.backBtn}>&larr; К переговорам</button>
        <span style={styles.topTitle}>AI-ПРОФИЛИ</span>
        <span style={{ flex: 1 }} />
        <button onClick={startNew} style={styles.newBtn}>+ Новый профиль</button>
      </div>

      {displayError && <div style={styles.error}>{displayError}</div>}
      {info && <div style={styles.info}>{info}</div>}

      <div style={styles.layout}>
        {/* список профилей */}
        <div style={styles.listCol}>
          {profiles.map((p) => (
            <div key={p.id} style={selectedId === p.id ? styles.profCardActive : styles.profCard}
                 onClick={() => selectProfile(p)}>
              <div style={styles.profName}>
                {p.name}{p.is_default && <span style={styles.defBadge}>по умолч.</span>}
              </div>
              <div style={styles.profMeta}>{p.suggestion_mode}</div>
              <div style={styles.profActions}>
                {!p.is_default && (
                  <button style={styles.smallBtn} disabled={busy}
                          onClick={(e) => { e.stopPropagation(); makeDefault(p.id); }}>Сделать default</button>
                )}
                {!p.is_default && (
                  <button style={styles.smallDanger} disabled={busy}
                          onClick={(e) => { e.stopPropagation(); remove(p.id); }}>Удалить</button>
                )}
              </div>
            </div>
          ))}
          {profiles.length === 0 && <div style={styles.muted}>Профилей пока нет.</div>}
        </div>

        {/* редактор */}
        {selectedId != null ? (
          <div style={styles.editCol}>
            <label style={styles.lbl}>Название</label>
            <input style={styles.input} value={draft.name || ''} onChange={(e) => set('name', e.target.value)} />

            <label style={styles.lbl}>Режим подсказок</label>
            <div style={styles.modeRow}>
              {MODES.map((m) => (
                <button key={m.key} title={m.hint}
                        style={draft.suggestion_mode === m.key ? styles.modeOn : styles.modeOff}
                        onClick={() => set('suggestion_mode', m.key)}>{m.label}</button>
              ))}
            </div>

            <div style={styles.grid2}>
              <div>
                <label style={styles.lbl}>STT-провайдер</label>
                <Select style={styles.input} value={draft.stt_provider || ''}
                        ariaLabel="STT-провайдер"
                        onChange={(v) => set('stt_provider', v || null)}
                        options={[{ value: '', label: 'по умолчанию' },
                          ...(options?.available_stt_providers || []).map((p) => ({ value: p, label: p }))]} />
              </div>
              <div>
                <label style={styles.lbl}>LLM-провайдер</label>
                <Select style={styles.input} value={draft.llm_provider || ''}
                        ariaLabel="LLM-провайдер"
                        onChange={(v) => set('llm_provider', v || null)}
                        options={[{ value: '', label: 'по умолчанию' },
                          ...(options?.available_llm_providers || []).map((p) => ({ value: p, label: p }))]} />
              </div>
            </div>

            {MODEL_FIELDS.map((f) => (
              <div key={f.key}>
                <label style={styles.lbl}>{f.label}</label>
                <Combobox style={styles.input}
                          value={(draft[f.key] as string) || ''}
                          placeholder="по умолчанию (из config)"
                          options={options?.available_llm_models || []}
                          onChange={(v) => set(f.key as keyof AISettingsProfileInput, (v || null) as never)} />
              </div>
            ))}

            <label style={styles.lbl}>Возможности</label>
            <div style={styles.toggles}>
              {TOGGLES.map((t) => (
                <label key={t.key} style={styles.toggle}>
                  <input type="checkbox" checked={!!draft[t.key as keyof AISettingsProfileInput]}
                         onChange={(e) => set(t.key as keyof AISettingsProfileInput, e.target.checked as never)} />
                  {t.label}
                </label>
              ))}
            </div>

            <button style={styles.advToggle} onClick={() => setAdvanced((v) => !v)}>
              {advanced ? '▾ Скрыть расширенные' : '▸ Расширенные лимиты'}
            </button>
            {advanced && (
              <div style={styles.grid2}>
                {LIMIT_FIELDS.map((f) => (
                  <div key={f.key}>
                    <label style={styles.lbl}>{f.label}</label>
                    <input type="number" style={styles.input}
                           value={(draft[f.key] as number | null) ?? ''}
                           onChange={(e) => set(f.key as keyof AISettingsProfileInput,
                             (e.target.value === '' ? null : Number(e.target.value)) as never)} />
                  </div>
                ))}
              </div>
            )}

            <div style={styles.saveRow}>
              <button style={styles.saveBtn} disabled={busy} onClick={save}>
                {selectedId === 'new' ? 'Создать профиль' : 'Сохранить'}
              </button>
            </div>
          </div>
        ) : (
          <div style={styles.editCol}>
            <div style={styles.muted}>Выберите профиль слева или создайте новый.</div>
          </div>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { padding: '28px 32px', display: 'flex', flexDirection: 'column', gap: 16, overflow: 'auto', flex: 1 },
  topBar: { display: 'flex', alignItems: 'center', gap: 16, paddingBottom: 14, borderBottom: `1px solid ${theme.border.default}` },
  backBtn: { display: 'flex', alignItems: 'center', gap: 6, padding: '6px 16px', background: 'transparent', border: `1px solid ${theme.accent.amber}`, borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono, flexShrink: 0 },
  topTitle: { fontFamily: theme.font.mono, fontSize: 11, letterSpacing: '0.16em', color: theme.text.secondary },
  newBtn: { padding: '6px 14px', background: theme.accent.amberGlow, border: `1px solid ${theme.accent.amber}`, borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono },
  layout: { display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' as const },
  listCol: { display: 'flex', flexDirection: 'column', gap: 8, width: 240, flexShrink: 0 },
  editCol: { display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minWidth: 320, maxWidth: 640, background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 18 },
  profCard: { padding: 12, background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 9, cursor: 'pointer' },
  profCardActive: { padding: 12, background: theme.bg.elevated, border: `1px solid ${theme.accent.amber}`, borderRadius: 9, cursor: 'pointer' },
  profName: { fontSize: 13, fontWeight: 600, color: theme.text.primary, display: 'flex', alignItems: 'center', gap: 6 },
  defBadge: { fontSize: 8, fontFamily: theme.font.mono, color: theme.accent.green, border: `1px solid ${theme.accent.green}`, borderRadius: 8, padding: '1px 6px' },
  profMeta: { fontSize: 10, fontFamily: theme.font.mono, color: theme.text.muted, marginTop: 3 },
  profActions: { display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' as const },
  smallBtn: { padding: '3px 8px', background: 'transparent', border: `1px solid ${theme.border.amber}`, borderRadius: 5, color: theme.accent.amber, cursor: 'pointer', fontSize: 9, fontFamily: theme.font.mono },
  smallDanger: { padding: '3px 8px', background: 'transparent', border: `1px solid ${theme.accent.red}`, borderRadius: 5, color: theme.accent.red, cursor: 'pointer', fontSize: 9, fontFamily: theme.font.mono },
  lbl: { fontSize: 10, fontFamily: theme.font.mono, color: theme.accent.amber, letterSpacing: '0.08em', textTransform: 'uppercase' as const, marginTop: 8 },
  input: { padding: '9px 12px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none', width: '100%', boxSizing: 'border-box' as const },
  grid2: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 },
  modeRow: { display: 'flex', gap: 8, flexWrap: 'wrap' as const },
  modeOn: { padding: '8px 14px', background: theme.accent.amberGlow, border: `1px solid ${theme.accent.amber}`, borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono },
  modeOff: { padding: '8px 14px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.secondary, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono },
  toggles: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 },
  toggle: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: theme.text.secondary, fontFamily: theme.font.body },
  advToggle: { alignSelf: 'flex-start', marginTop: 10, padding: '4px 0', background: 'transparent', border: 'none', color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono },
  saveRow: { display: 'flex', gap: 10, marginTop: 12 },
  saveBtn: { padding: '10px 18px', background: theme.accent.amber, border: 'none', borderRadius: 8, color: '#080A0F', cursor: 'pointer', fontSize: 12, fontWeight: 600, fontFamily: theme.font.body },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 12 },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 12 },
  info: { color: theme.accent.green, fontFamily: theme.font.mono, fontSize: 12 },
};
