import { useState } from 'react';
import { theme } from '../styles/theme';
import { Select, Combobox, TextInput } from '../components/common';
import { apiErrorMessage } from '../lib/apiError';
import {
  useProfiles, useAiOptions, useCreateProfile, useUpdateProfile, useDeleteProfile, useMakeDefaultProfile,
} from '../hooks/queries/aiSettings';
import type { AISettingsProfile, AISettingsProfileInput, SuggestionMode } from '../types';
import styles from './AISettingsPage.module.css';
import { cx } from '../utils/cx';

interface Props {
  onBack?: () => void;
  /** Внутри хаба настроек: без своей шапки «назад» и заголовка */
  embedded?: boolean;
}

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

export function AISettingsPage({ onBack, embedded }: Props) {
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
    <div className={embedded ? styles.containerEmbedded : styles.container}>
      <div className={styles.topBar}>
        {!embedded && onBack && <button onClick={onBack} className={styles.backBtn}>&larr; К переговорам</button>}
        {!embedded && <span className={styles.topTitle}>AI-ПРОФИЛИ</span>}
        <span className={styles.spacer} />
        <button onClick={startNew} className={styles.newBtn}>+ Новый профиль</button>
      </div>

      {displayError && <div className={styles.error}>{displayError}</div>}
      {info && <div className={styles.info}>{info}</div>}

      <div className={styles.layout}>
        {/* список профилей */}
        <div className={styles.listCol}>
          {profiles.map((p) => (
            <div key={p.id} className={cx(selectedId === p.id ? styles.profCardActive : styles.profCard)}
                 onClick={() => selectProfile(p)}>
              <div className={styles.profName}>
                {p.name}{p.is_default && <span className={styles.defBadge}>по умолч.</span>}
              </div>
              <div className={styles.profMeta}>{p.suggestion_mode}</div>
              <div className={styles.profActions}>
                {!p.is_default && (
                  <button className={styles.smallBtn} disabled={busy}
                          onClick={(e) => { e.stopPropagation(); makeDefault(p.id); }}>Сделать default</button>
                )}
                {!p.is_default && (
                  <button className={styles.smallDanger} disabled={busy}
                          onClick={(e) => { e.stopPropagation(); remove(p.id); }}>Удалить</button>
                )}
              </div>
            </div>
          ))}
          {profiles.length === 0 && <div className={styles.muted}>Профилей пока нет.</div>}
        </div>

        {/* редактор */}
        {selectedId != null ? (
          <div className={styles.editCol}>
            <label className={styles.lbl}>Название</label>
            <TextInput inputClassName={styles.input} value={draft.name || ''} onChange={(e) => set('name', e.target.value)} onClear={() => set('name', '')} clearLabel="название" />

            <label className={styles.lbl}>Режим подсказок</label>
            <div className={styles.modeRow}>
              {MODES.map((m) => (
                <button key={m.key} title={m.hint}
                        className={cx(draft.suggestion_mode === m.key ? styles.modeOn : styles.modeOff)}
                        onClick={() => set('suggestion_mode', m.key)}>{m.label}</button>
              ))}
            </div>

            <div className={styles.grid2}>
              <div>
                <label className={styles.lbl}>STT-провайдер</label>
                <Select style={fieldStyle} value={draft.stt_provider || ''}
                        ariaLabel="STT-провайдер"
                        onChange={(v) => set('stt_provider', v || null)}
                        options={[{ value: '', label: 'по умолчанию' },
                          ...(options?.available_stt_providers || []).map((p) => ({ value: p, label: p }))]} />
              </div>
              <div>
                <label className={styles.lbl}>LLM-провайдер</label>
                <Select style={fieldStyle} value={draft.llm_provider || ''}
                        ariaLabel="LLM-провайдер"
                        onChange={(v) => set('llm_provider', v || null)}
                        options={[{ value: '', label: 'по умолчанию' },
                          ...(options?.available_llm_providers || []).map((p) => ({ value: p, label: p }))]} />
              </div>
            </div>

            {MODEL_FIELDS.map((f) => (
              <div key={f.key}>
                <label className={styles.lbl}>{f.label}</label>
                <Combobox style={fieldStyle}
                          value={(draft[f.key] as string) || ''}
                          placeholder="по умолчанию (из config)"
                          options={options?.available_llm_models || []}
                          onChange={(v) => set(f.key as keyof AISettingsProfileInput, (v || null) as never)} />
              </div>
            ))}

            <label className={styles.lbl}>Возможности</label>
            <div className={styles.toggles}>
              {TOGGLES.map((t) => (
                <label key={t.key} className={styles.toggle}>
                  <input type="checkbox" checked={!!draft[t.key as keyof AISettingsProfileInput]}
                         onChange={(e) => set(t.key as keyof AISettingsProfileInput, e.target.checked as never)} />
                  {t.label}
                </label>
              ))}
            </div>

            <button className={styles.advToggle} onClick={() => setAdvanced((v) => !v)}>
              {advanced ? '▾ Скрыть расширенные' : '▸ Расширенные лимиты'}
            </button>
            {advanced && (
              <div className={styles.grid2}>
                {LIMIT_FIELDS.map((f) => (
                  <div key={f.key}>
                    <label className={styles.lbl}>{f.label}</label>
                    <TextInput type="number" inputClassName={styles.input}
                           value={(draft[f.key] as number | null) ?? ''}
                           onChange={(e) => set(f.key as keyof AISettingsProfileInput,
                             (e.target.value === '' ? null : Number(e.target.value)) as never)}
                           onClear={() => set(f.key as keyof AISettingsProfileInput, null as never)}
                           clearLabel={f.label} />
                  </div>
                ))}
              </div>
            )}

            <div className={styles.saveRow}>
              <button className={styles.saveBtn} disabled={busy} onClick={save}>
                {selectedId === 'new' ? 'Создать профиль' : 'Сохранить'}
              </button>
            </div>
          </div>
        ) : (
          <div className={styles.editCol}>
            <div className={styles.muted}>Выберите профиль слева или создайте новый.</div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Стиль <Select>/<Combobox>: компоненты принимают только style (не className). */
const fieldStyle: React.CSSProperties = {
  padding: '9px 12px',
  background: theme.bg.input,
  border: `1px solid ${theme.border.default}`,
  borderRadius: 7,
  color: theme.text.primary,
  fontSize: 13,
  fontFamily: theme.font.body,
  outline: 'none',
  width: '100%',
  boxSizing: 'border-box',
};
