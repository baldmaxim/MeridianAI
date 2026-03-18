import { useState } from 'react';
import { theme } from '../../styles/theme';
import type { SuggestionTypeConfig, TriggerKeywordConfig } from '../../types';

interface Props {
  suggestionTypes: SuggestionTypeConfig[];
  triggerKeywords: TriggerKeywordConfig[];
  onSuggestionTypesChange: (types: SuggestionTypeConfig[]) => void;
  onTriggerKeywordsChange: (keywords: TriggerKeywordConfig[]) => void;
}

function Toggle({ checked, onToggle }: { checked: boolean; onToggle: () => void }) {
  return (
    <div
      style={{
        ...styles.toggle,
        background: checked ? theme.accent.amber : theme.bg.elevated,
        justifyContent: checked ? 'flex-end' : 'flex-start',
      }}
      onClick={onToggle}
    >
      <div style={styles.toggleKnob} />
    </div>
  );
}

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16) || 0;
  const g = parseInt(hex.slice(3, 5), 16) || 0;
  const b = parseInt(hex.slice(5, 7), 16) || 0;
  return `rgba(${r},${g},${b},${alpha})`;
}

export function HintsSettings({ suggestionTypes, triggerKeywords, onSuggestionTypesChange, onTriggerKeywordsChange }: Props) {
  const [expandedType, setExpandedType] = useState<string | null>(null);

  const updateType = (key: string, patch: Partial<SuggestionTypeConfig>) => {
    onSuggestionTypesChange(
      suggestionTypes.map((t) => (t.key === key ? { ...t, ...patch } : t))
    );
  };

  const removeType = (key: string) => {
    onSuggestionTypesChange(suggestionTypes.filter((t) => t.key !== key));
  };

  const addType = () => {
    const id = `custom_${Date.now()}`;
    onSuggestionTypesChange([
      ...suggestionTypes,
      {
        key: id,
        badge: 'НОВЫЙ ТИП',
        color: '#8896B3',
        metaLabel: 'Контекст',
        actionLabel: 'Использовать',
        llm_description: 'описание для LLM — когда использовать этот тип подсказки',
        enabled: true,
      },
    ]);
    setExpandedType(id);
  };

  const updateKeyword = (idx: number, patch: Partial<TriggerKeywordConfig>) => {
    const updated = [...triggerKeywords];
    updated[idx] = { ...updated[idx], ...patch };
    onTriggerKeywordsChange(updated);
  };

  const removeKeyword = (idx: number) => {
    onTriggerKeywordsChange(triggerKeywords.filter((_, i) => i !== idx));
  };

  const addKeyword = () => {
    onTriggerKeywordsChange([
      ...triggerKeywords,
      { keyword: '', status_message: 'Анализирую...', enabled: true },
    ]);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Suggestion Types */}
      <div style={styles.card}>
        <div style={styles.cardHeader}>
          <span style={styles.dot} />
          <span style={styles.cardTitle}>Типы подсказок</span>
          <span style={styles.countBadge}>{suggestionTypes.filter((t) => t.enabled).length} активных</span>
        </div>
        <div style={styles.hint}>Определяют категории подсказок от AI. Описание используется в промпте для LLM.</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {suggestionTypes.map((t) => {
            const expanded = expandedType === t.key;
            return (
              <div key={t.key} style={{
                ...styles.typeItem,
                borderLeftColor: t.color,
                opacity: t.enabled ? 1 : 0.5,
              }}>
                {/* Header row */}
                <div style={styles.typeHeader}>
                  <div
                    style={{ ...styles.colorSwatch, background: t.color }}
                    title={t.color}
                  />
                  <input
                    value={t.badge}
                    onChange={(e) => updateType(t.key, { badge: e.target.value })}
                    style={styles.badgeInput}
                    placeholder="Бейдж"
                  />
                  <Toggle checked={t.enabled} onToggle={() => updateType(t.key, { enabled: !t.enabled })} />
                  <button
                    style={styles.expandBtn}
                    onClick={() => setExpandedType(expanded ? null : t.key)}
                    title="Подробнее"
                  >
                    {expanded ? '▲' : '▼'}
                  </button>
                  <button
                    style={styles.deleteBtn}
                    onClick={() => removeType(t.key)}
                    title="Удалить"
                  >
                    ✕
                  </button>
                </div>

                {/* Expanded details */}
                {expanded && (
                  <div style={styles.typeDetails}>
                    <div style={styles.fieldRow}>
                      <div style={styles.fieldCol}>
                        <label style={styles.fieldLabel}>Ключ (key)</label>
                        <input
                          value={t.key}
                          onChange={(e) => {
                            const newKey = e.target.value.replace(/[^a-z0-9_]/g, '');
                            const updated = suggestionTypes.map((st) =>
                              st.key === t.key ? { ...st, key: newKey } : st
                            );
                            onSuggestionTypesChange(updated);
                            setExpandedType(newKey);
                          }}
                          style={styles.input}
                          placeholder="snake_case"
                        />
                      </div>
                      <div style={styles.fieldCol}>
                        <label style={styles.fieldLabel}>Цвет</label>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <input
                            type="color"
                            value={t.color}
                            onChange={(e) => updateType(t.key, { color: e.target.value })}
                            style={styles.colorPicker}
                          />
                          <input
                            value={t.color}
                            onChange={(e) => updateType(t.key, { color: e.target.value })}
                            style={{ ...styles.input, flex: 1 }}
                            placeholder="#FF4B6E"
                          />
                        </div>
                      </div>
                    </div>
                    <div style={styles.fieldRow}>
                      <div style={styles.fieldCol}>
                        <label style={styles.fieldLabel}>Мета-лейбл</label>
                        <input
                          value={t.metaLabel || ''}
                          onChange={(e) => updateType(t.key, { metaLabel: e.target.value || undefined })}
                          style={styles.input}
                          placeholder="Паттерн / Метод / Триггер"
                        />
                      </div>
                      <div style={styles.fieldCol}>
                        <label style={styles.fieldLabel}>Кнопка действия</label>
                        <input
                          value={t.actionLabel}
                          onChange={(e) => updateType(t.key, { actionLabel: e.target.value })}
                          style={styles.input}
                          placeholder="Использовать"
                        />
                      </div>
                    </div>
                    <div style={styles.fieldCol}>
                      <label style={styles.fieldLabel}>Описание для LLM</label>
                      <textarea
                        value={t.llm_description}
                        onChange={(e) => updateType(t.key, { llm_description: e.target.value })}
                        style={styles.textarea}
                        rows={3}
                        placeholder="Описание типа подсказки для LLM..."
                      />
                    </div>
                    {/* Preview */}
                    <div style={{ marginTop: 8 }}>
                      <label style={styles.fieldLabel}>Превью</label>
                      <div style={{
                        borderLeft: `3px solid ${t.color}`,
                        background: hexToRgba(t.color, 0.06),
                        borderRadius: 6,
                        padding: '8px 12px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                      }}>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: 4,
                          fontSize: 9,
                          fontFamily: theme.font.mono,
                          fontWeight: 600,
                          letterSpacing: '0.08em',
                          color: t.color,
                          background: hexToRgba(t.color, 0.1),
                          border: `1px solid ${hexToRgba(t.color, 0.25)}`,
                          textTransform: 'uppercase',
                        }}>
                          {t.badge}
                        </span>
                        <span style={{ fontSize: 11, color: theme.text.muted, fontFamily: theme.font.mono }}>
                          {t.metaLabel && `— ${t.metaLabel}: ...`}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <button style={styles.addBtn} onClick={addType}>+ Добавить тип</button>
      </div>

      {/* Trigger Keywords */}
      <div style={styles.card}>
        <div style={styles.cardHeader}>
          <span style={styles.dot} />
          <span style={styles.cardTitle}>Триггеры авто-подсказок</span>
          <span style={styles.countBadge}>{triggerKeywords.filter((k) => k.enabled).length} активных</span>
        </div>
        <div style={styles.hint}>Ключевые слова в речи, при обнаружении которых AI автоматически даёт подсказку.</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {triggerKeywords.map((kw, i) => (
            <div key={i} style={{
              ...styles.kwRow,
              opacity: kw.enabled ? 1 : 0.5,
            }}>
              <input
                value={kw.keyword}
                onChange={(e) => updateKeyword(i, { keyword: e.target.value })}
                style={{ ...styles.input, flex: 1, minWidth: 80 }}
                placeholder="ключевое слово"
              />
              <input
                value={kw.status_message}
                onChange={(e) => updateKeyword(i, { status_message: e.target.value })}
                style={{ ...styles.input, flex: 2 }}
                placeholder="Статус сообщение..."
              />
              <Toggle checked={kw.enabled} onToggle={() => updateKeyword(i, { enabled: !kw.enabled })} />
              <button style={styles.deleteBtn} onClick={() => removeKeyword(i)} title="Удалить">✕</button>
            </div>
          ))}
        </div>

        <button style={styles.addBtn} onClick={addKeyword}>+ Добавить триггер</button>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 24,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  dot: {
    width: 6, height: 6, borderRadius: '50%',
    background: theme.accent.amber, flexShrink: 0,
  },
  cardTitle: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11,
    letterSpacing: '0.14em', textTransform: 'uppercase' as const,
    color: theme.text.primary, flex: 1,
  },
  countBadge: {
    padding: '3px 10px',
    background: 'rgba(245,166,35,0.12)',
    border: '1px solid rgba(245,166,35,0.25)',
    borderRadius: 5,
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.accent.amber,
  },
  hint: {
    fontSize: 11,
    color: theme.text.muted,
    fontFamily: theme.font.body,
    lineHeight: 1.4,
  },
  typeItem: {
    background: theme.bg.elevated,
    border: `1px solid ${theme.border.default}`,
    borderLeft: '3px solid',
    borderRadius: 8,
    padding: '10px 14px',
  },
  typeHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  colorSwatch: {
    width: 16, height: 16, borderRadius: 4, flexShrink: 0,
    border: `1px solid ${theme.border.default}`,
  },
  badgeInput: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    color: theme.text.primary,
    fontSize: 12,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.06em',
    outline: 'none',
    padding: '4px 0',
  },
  expandBtn: {
    background: 'transparent',
    border: 'none',
    color: theme.text.muted,
    fontSize: 10,
    cursor: 'pointer',
    padding: '4px 6px',
  },
  deleteBtn: {
    background: 'transparent',
    border: 'none',
    color: theme.text.muted,
    fontSize: 12,
    cursor: 'pointer',
    padding: '4px 6px',
  },
  typeDetails: {
    marginTop: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    paddingTop: 12,
    borderTop: `1px solid ${theme.border.default}`,
  },
  fieldRow: {
    display: 'flex',
    gap: 10,
  },
  fieldCol: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  fieldLabel: {
    fontSize: 9,
    fontFamily: theme.font.mono,
    color: theme.text.muted,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
  },
  input: {
    padding: '7px 10px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 6,
    color: theme.text.primary,
    fontSize: 12,
    fontFamily: theme.font.body,
    outline: 'none',
  },
  textarea: {
    padding: '7px 10px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 6,
    color: theme.text.primary,
    fontSize: 12,
    fontFamily: theme.font.body,
    outline: 'none',
    resize: 'vertical' as const,
    lineHeight: 1.5,
  },
  colorPicker: {
    width: 28, height: 28, padding: 0, border: 'none',
    borderRadius: 4, cursor: 'pointer', background: 'transparent',
  },
  addBtn: {
    padding: '8px 14px',
    background: theme.bg.elevated,
    border: `1px dashed ${theme.border.default}`,
    borderRadius: 8,
    color: theme.text.muted,
    fontSize: 12,
    fontFamily: theme.font.body,
    cursor: 'pointer',
    textAlign: 'center' as const,
  },
  kwRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '4px 0',
  },
  toggle: {
    width: 36, height: 20, borderRadius: 10,
    display: 'flex', alignItems: 'center', padding: 2,
    flexShrink: 0, cursor: 'pointer', transition: 'background 0.2s',
  },
  toggleKnob: {
    width: 16, height: 16, borderRadius: '50%', background: '#fff',
  },
};
