import type { CSSProperties, FC } from 'react';
import type { SuggestionTypeConfig } from '../../types';
import { IconSwap } from '../common/IconSwap';
import { Collapse, TextInput } from '../common';
import { HintsToggle } from './HintsToggle';
import styles from './SuggestionTypeItem.module.css';
import { cx } from '../../utils/cx';

interface ISuggestionTypeItemProps {
  type: SuggestionTypeConfig;
  expanded: boolean;
  onToggleExpand: () => void;
  onUpdate: (patch: Partial<SuggestionTypeConfig>) => void;
  onRename: (newKey: string) => void;
  onRemove: () => void;
}

/** Цвет типа подсказки — пользовательские данные (hex из input[type=color]), передаём в CSS через переменную. */
type ColorVars = CSSProperties & { '--hint-color': string };

/** Карточка одного типа подсказки: заголовок + раскрывающиеся настройки. */
export const SuggestionTypeItem: FC<ISuggestionTypeItemProps> = ({
  type: t, expanded, onToggleExpand, onUpdate, onRename, onRemove,
}) => {
  const colorVars: ColorVars = { '--hint-color': t.color };
  return (
    <div className={cx(styles.typeItem, !t.enabled && styles.typeItemOff)} style={colorVars}>
      {/* Header row */}
      <div className={styles.typeHeader}>
        <div className={styles.colorSwatch} title={t.color} />
        <TextInput
          className={styles.badgeField}
          inputClassName={styles.badgeInput}
          value={t.badge}
          onChange={(e) => onUpdate({ badge: e.target.value })}
          onClear={() => onUpdate({ badge: '' })}
          clearLabel="бейдж"
          placeholder="Бейдж"
        />
        <HintsToggle checked={t.enabled} onToggle={() => onUpdate({ enabled: !t.enabled })} />
        <button className={styles.expandBtn} onClick={onToggleExpand} title="Подробнее">
          <IconSwap state={expanded ? 'b' : 'a'} a="▼" b="▲" />
        </button>
        <button className={styles.deleteBtn} onClick={onRemove} title="Удалить">
          ✕
        </button>
      </div>

      {/* Expanded details */}
      <Collapse open={expanded}>
        <div className={styles.typeDetails}>
          <div className={styles.fieldRow}>
            <div className={styles.fieldCol}>
              <label className={styles.fieldLabel}>Ключ (key)</label>
              <TextInput
                value={t.key}
                onChange={(e) => onRename(e.target.value.replace(/[^a-z0-9_]/g, ''))}
                onClear={() => onRename('')}
                clearLabel="ключ"
                inputClassName={styles.input}
                placeholder="snake_case"
              />
            </div>
            <div className={styles.fieldCol}>
              <label className={styles.fieldLabel}>Цвет</label>
              <div className={styles.colorRow}>
                <input
                  type="color"
                  value={t.color}
                  onChange={(e) => onUpdate({ color: e.target.value })}
                  className={styles.colorPicker}
                />
                <TextInput
                  value={t.color}
                  onChange={(e) => onUpdate({ color: e.target.value })}
                  onClear={() => onUpdate({ color: '' })}
                  clearLabel="цвет"
                  className={styles.colorField}
                  inputClassName={styles.input}
                  placeholder="#FF4B6E"
                />
              </div>
            </div>
          </div>
          <div className={styles.fieldRow}>
            <div className={styles.fieldCol}>
              <label className={styles.fieldLabel}>Мета-лейбл</label>
              <TextInput
                value={t.metaLabel || ''}
                onChange={(e) => onUpdate({ metaLabel: e.target.value || undefined })}
                onClear={() => onUpdate({ metaLabel: undefined })}
                clearLabel="мета-лейбл"
                inputClassName={styles.input}
                placeholder="Паттерн / Метод / Триггер"
              />
            </div>
            <div className={styles.fieldCol}>
              <label className={styles.fieldLabel}>Кнопка действия</label>
              <TextInput
                value={t.actionLabel}
                onChange={(e) => onUpdate({ actionLabel: e.target.value })}
                onClear={() => onUpdate({ actionLabel: '' })}
                clearLabel="кнопку действия"
                inputClassName={styles.input}
                placeholder="Использовать"
              />
            </div>
          </div>
          <div className={styles.fieldCol}>
            <label className={styles.fieldLabel}>Описание для LLM</label>
            <textarea
              value={t.llm_description}
              onChange={(e) => onUpdate({ llm_description: e.target.value })}
              className={styles.textarea}
              rows={3}
              placeholder="Описание типа подсказки для LLM..."
            />
          </div>
          {/* Preview */}
          <div className={styles.previewWrap}>
            <label className={styles.fieldLabel}>Превью</label>
            <div className={styles.preview}>
              <span className={styles.previewBadge}>{t.badge}</span>
              <span className={styles.previewMeta}>{t.metaLabel && `— ${t.metaLabel}: ...`}</span>
            </div>
          </div>
        </div>
      </Collapse>
    </div>
  );
};
