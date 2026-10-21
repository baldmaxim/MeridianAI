import { useState } from 'react';
import type { SuggestionTypeConfig, TriggerKeywordConfig } from '../../types';
import { TextInput } from '../common';
import { HintsToggle } from './HintsToggle';
import { SuggestionTypeItem } from './SuggestionTypeItem';
import styles from './HintsSettings.module.css';
import { cx } from '../../utils/cx';

interface Props {
  suggestionTypes: SuggestionTypeConfig[];
  triggerKeywords: TriggerKeywordConfig[];
  onSuggestionTypesChange: (types: SuggestionTypeConfig[]) => void;
  onTriggerKeywordsChange: (keywords: TriggerKeywordConfig[]) => void;
}

export function HintsSettings({ suggestionTypes, triggerKeywords, onSuggestionTypesChange, onTriggerKeywordsChange }: Props) {
  const [expandedType, setExpandedType] = useState<string | null>(null);

  const updateType = (key: string, patch: Partial<SuggestionTypeConfig>) => {
    onSuggestionTypesChange(
      suggestionTypes.map((t) => (t.key === key ? { ...t, ...patch } : t))
    );
  };

  const renameType = (key: string, newKey: string) => {
    onSuggestionTypesChange(
      suggestionTypes.map((st) => (st.key === key ? { ...st, key: newKey } : st))
    );
    setExpandedType(newKey);
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
        // цвет — пользовательские данные (hex: нужен для input[type=color] и хранится в настройках)
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
    <div className={styles.root}>
      {/* Suggestion Types */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <span className={styles.dot} />
          <span className={styles.cardTitle}>Типы подсказок</span>
          <span className={styles.countBadge}>{suggestionTypes.filter((t) => t.enabled).length} активных</span>
        </div>
        <div className={styles.hint}>Определяют категории подсказок от AI. Описание используется в промпте для LLM.</div>

        <div className={styles.typeList}>
          {suggestionTypes.map((t) => (
            <SuggestionTypeItem
              key={t.key}
              type={t}
              expanded={expandedType === t.key}
              onToggleExpand={() => setExpandedType(expandedType === t.key ? null : t.key)}
              onUpdate={(patch) => updateType(t.key, patch)}
              onRename={(newKey) => renameType(t.key, newKey)}
              onRemove={() => removeType(t.key)}
            />
          ))}
        </div>

        <button className={styles.addBtn} onClick={addType}>+ Добавить тип</button>
      </div>

      {/* Trigger Keywords */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <span className={styles.dot} />
          <span className={styles.cardTitle}>Триггеры авто-подсказок</span>
          <span className={styles.countBadge}>{triggerKeywords.filter((k) => k.enabled).length} активных</span>
        </div>
        <div className={styles.hint}>Ключевые слова в речи, при обнаружении которых AI автоматически даёт подсказку.</div>

        <div className={styles.kwList}>
          {triggerKeywords.map((kw, i) => (
            <div key={i} className={cx(styles.kwRow, !kw.enabled && styles.kwRowOff)}>
              <TextInput
                value={kw.keyword}
                onChange={(e) => updateKeyword(i, { keyword: e.target.value })}
                onClear={() => updateKeyword(i, { keyword: '' })}
                clearLabel="ключевое слово"
                className={styles.keywordField}
                inputClassName={styles.input}
                placeholder="ключевое слово"
              />
              <TextInput
                value={kw.status_message}
                onChange={(e) => updateKeyword(i, { status_message: e.target.value })}
                onClear={() => updateKeyword(i, { status_message: '' })}
                clearLabel="статус-сообщение"
                className={styles.messageField}
                inputClassName={styles.input}
                placeholder="Статус сообщение..."
              />
              <HintsToggle checked={kw.enabled} onToggle={() => updateKeyword(i, { enabled: !kw.enabled })} />
              <button className={styles.deleteBtn} onClick={() => removeKeyword(i)} title="Удалить">✕</button>
            </div>
          ))}
        </div>

        <button className={styles.addBtn} onClick={addKeyword}>+ Добавить триггер</button>
      </div>
    </div>
  );
}
