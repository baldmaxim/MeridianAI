import { theme } from '../../styles/theme';
import type { ContextSourceKind, ContextSourceUiStatus, ContextSourceViewModel } from './contextSourceModel';

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

function statusColor(s: ContextSourceUiStatus): string {
  if (s === 'ready') return theme.accent.green;
  if (s === 'error') return theme.accent.red;
  if (s === 'processing') return theme.accent.amber;
  return theme.text.muted;
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
    <div style={{ ...styles.card, ...(compact ? styles.cardCompact : {}), ...(disabled ? styles.cardDisabled : {}) }}>
      <span style={styles.icon} aria-hidden>{KIND_ICON[source.kind]}</span>

      <div style={styles.main}>
        <div style={styles.title} title={source.title}>{source.title}</div>
        {source.subtitle && <div style={styles.subtitle}>{source.subtitle}</div>}
        <div style={styles.metaRow}>
          {showStatus && (
            <span style={{ ...styles.statusBadge, color: statusColor(source.status) }}>
              ● {source.statusLabel}
            </span>
          )}
          {source.meta && <span style={styles.meta}>{source.meta}</span>}
        </div>
      </div>

      <div style={styles.controls}>
        {right}

        {!right && primaryActionLabel && (
          <button
            type="button"
            style={disabled || !onPrimaryAction ? styles.primaryBtnDisabled : styles.primaryBtn}
            onClick={onPrimaryAction}
            disabled={disabled || !onPrimaryAction}
          >
            {primaryActionLabel}
          </button>
        )}

        {!readOnly && onPriorityChange && (
          <input
            type="number"
            value={source.priority ?? 0}
            title="Приоритет (меньше — выше)"
            onChange={(e) => onPriorityChange(Number(e.target.value))}
            style={styles.priority}
            disabled={disabled}
          />
        )}

        {!readOnly && onToggleIncluded && (
          <button
            type="button"
            style={source.included ? styles.toggleOn : styles.toggleOff}
            onClick={onToggleIncluded}
            disabled={disabled}
            title={source.included ? 'В контексте — выключить' : 'Включить в контекст'}
          >
            {source.included ? 'в контексте' : 'выкл'}
          </button>
        )}

        {readOnly && !right && !onPrimaryAction && (
          <span style={source.included ? styles.badgeOn : styles.badgeOff}>
            {source.included ? 'в контексте' : 'выкл'}
          </span>
        )}

        {!readOnly && onRemove && (
          <button type="button" style={styles.removeBtn} onClick={onRemove} title="Удалить из контекста">✕</button>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    display: 'flex', alignItems: 'flex-start', gap: 10,
    padding: '10px 12px', background: theme.bg.elevated,
    border: `1px solid ${theme.border.default}`, borderRadius: 8,
  },
  cardCompact: { padding: '8px 10px', background: theme.bg.input },
  cardDisabled: { opacity: 0.55 },
  icon: { fontSize: 14, lineHeight: '20px', flexShrink: 0, width: 18, textAlign: 'center' as const },
  main: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 },
  title: {
    fontSize: 13, fontWeight: 600, color: theme.text.primary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  },
  subtitle: { fontSize: 12, color: theme.text.secondary, lineHeight: 1.4 },
  metaRow: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const, marginTop: 1 },
  statusBadge: { fontFamily: theme.font.mono, fontSize: 10, flexShrink: 0 },
  meta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  controls: { display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 },
  primaryBtn: {
    padding: '6px 12px', background: theme.accent.green, border: 'none', borderRadius: 6,
    color: '#080A0F', cursor: 'pointer', fontSize: 11, fontWeight: 600, fontFamily: theme.font.body,
  },
  primaryBtnDisabled: {
    padding: '6px 12px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 6, color: theme.text.muted, cursor: 'not-allowed', fontSize: 11,
    fontFamily: theme.font.body, opacity: 0.6,
  },
  priority: {
    width: 46, padding: '4px 6px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 5,
    color: theme.text.primary, fontSize: 11, fontFamily: theme.font.mono,
  },
  toggleOn: {
    padding: '5px 10px', background: 'rgba(46,229,157,0.1)',
    border: '1px solid rgba(46,229,157,0.25)', borderRadius: 6,
    color: theme.accent.green, cursor: 'pointer', fontSize: 9, fontFamily: theme.font.mono,
  },
  toggleOff: {
    padding: '5px 10px', background: 'transparent',
    border: `1px solid ${theme.border.default}`, borderRadius: 6,
    color: theme.text.muted, cursor: 'pointer', fontSize: 9, fontFamily: theme.font.mono,
  },
  badgeOn: {
    padding: '3px 9px', border: `1px solid ${theme.accent.green}`, borderRadius: 10,
    fontFamily: theme.font.mono, fontSize: 9, color: theme.accent.green,
  },
  badgeOff: {
    padding: '3px 9px', border: `1px solid ${theme.border.default}`, borderRadius: 10,
    fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted,
  },
  removeBtn: {
    padding: '5px 9px', background: 'transparent',
    border: `1px solid ${theme.accent.red}`, borderRadius: 6,
    color: theme.accent.red, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
};
