import type { ContextSourceKind, ContextSourceUiStatus, ContextSourceViewModel } from './contextSourceModel';
import styles from './ContextSourceCard.module.css';

interface ContextSourceCardProps {
  source: ContextSourceViewModel;
  readOnly?: boolean;
  compact?: boolean;
  right?: React.ReactNode;
  onToggleIncluded?: () => void;
  onRemove?: () => void;
  onPriorityChange?: (priority: number) => void;
  onPrimaryAction?: () => void;
  primaryActionLabel?: string;
}

const KIND_ICON: Record<ContextSourceKind, string> = {
  document: '📄',
  previous_meeting: '🗓',
  rag_folder: '📁',
  letter: '✉',
  manual: '◆',
  knowledge: '◆',
  customer_profile: '◆',
  object_profile: '◆',
};

function statusClass(s: ContextSourceUiStatus): string {
  if (s === 'ready') return styles.statusReady;
  if (s === 'error') return styles.statusError;
  if (s === 'processing') return styles.statusProcessing;
  if (s === 'awaiting') return styles.statusAwaiting;
  return styles.statusIdle;
}

// Единая карточка источника контекста: документ, прошлая встреча, RAG-папка.
// Вся карточка НЕ кликабельна — включение/выключение только через кнопку.
export function ContextSourceCard({
  source, readOnly, compact, right,
  onToggleIncluded, onRemove, onPriorityChange, onPrimaryAction, primaryActionLabel,
}: ContextSourceCardProps) {
  const disabled = !!source.disabled;
  const showStatus = !!source.statusLabel && source.status !== 'ready';

  return (
    <div className={`${styles.card} ${compact ? styles.cardCompact : ''} ${disabled ? styles.cardDisabled : ''}`}>
      <span className={styles.icon} aria-hidden>{KIND_ICON[source.kind]}</span>

      <div className={styles.main}>
        <div className={styles.title} title={source.title}>{source.title}</div>
        {source.subtitle && <div className={styles.subtitle}>{source.subtitle}</div>}
        <div className={styles.metaRow}>
          {showStatus && (
            <span className={`${styles.statusBadge} ${statusClass(source.status)}`}>
              ● {source.statusLabel}
            </span>
          )}
          {source.meta && <span className={styles.meta}>{source.meta}</span>}
        </div>
      </div>

      <div className={styles.controls}>
        {right}

        {!right && primaryActionLabel && (
          <button
            type="button"
            className={disabled || !onPrimaryAction ? styles.primaryBtnDisabled : styles.primaryBtn}
            onClick={onPrimaryAction}
            disabled={disabled || !onPrimaryAction}
          >
            {primaryActionLabel}
          </button>
        )}

        {!readOnly && onPriorityChange && (
          // Исключение из правила «крестик в поле»: узкий счётчик приоритета (46px), значение всегда задано
          <input
            type="number"
            value={source.priority ?? 0}
            title="Приоритет (меньше — выше)"
            onChange={(e) => onPriorityChange(Number(e.target.value))}
            className={styles.priority}
            disabled={disabled}
          />
        )}

        {!readOnly && onToggleIncluded && (
          <button
            type="button"
            className={source.included ? styles.toggleOn : styles.toggleOff}
            onClick={onToggleIncluded}
            disabled={disabled}
            title={source.included ? 'В контексте — выключить' : 'Включить в контекст'}
          >
            {source.included ? 'в контексте' : 'выкл'}
          </button>
        )}

        {readOnly && !right && !onPrimaryAction && (
          <span className={source.included ? styles.badgeOn : styles.badgeOff}>
            {source.included ? 'в контексте' : 'выкл'}
          </span>
        )}

        {!readOnly && onRemove && (
          <button type="button" className={styles.removeBtn} onClick={onRemove} title="Удалить из контекста">✕</button>
        )}
      </div>
    </div>
  );
}
