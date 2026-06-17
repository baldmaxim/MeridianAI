import { theme } from '../../styles/theme';
import { formatFileSize } from '../../lib/documentFiles';
import type { DocumentUploadQueueItem, DocumentUploadQueueStatus } from '../../hooks/useDocumentUploadQueue';

interface DocumentUploadQueueProps {
  items: DocumentUploadQueueItem[];
  onRetry: (clientId: string) => void;
  onCancel: (clientId: string) => void;
  onClearItem: (clientId: string) => void;
  onClearFinished: () => void;
}

const STATUS_LABELS: Record<DocumentUploadQueueStatus, string> = {
  queued: 'в очереди',
  creating_session: 'подготовка',
  uploading: 'загрузка в S3',
  confirming: 'подтверждение',
  attaching: 'добавление в контекст',
  processing: 'обработка',
  done: 'добавлен',
  error: 'ошибка',
  cancelled: 'отменено',
};

const PROGRESS_STATUSES: ReadonlySet<DocumentUploadQueueStatus> = new Set([
  'uploading', 'confirming', 'attaching',
]);
const CANCELABLE: ReadonlySet<DocumentUploadQueueStatus> = new Set([
  'queued', 'creating_session', 'uploading',
]);
const CLEARABLE: ReadonlySet<DocumentUploadQueueStatus> = new Set([
  'done', 'error', 'cancelled',
]);

function statusColor(s: DocumentUploadQueueStatus): string {
  if (s === 'done') return theme.accent.green;
  if (s === 'error') return theme.accent.red;
  if (s === 'cancelled') return theme.text.muted;
  if (s === 'queued') return theme.text.secondary;
  return theme.accent.amber;
}

export function DocumentUploadQueue({ items, onRetry, onCancel, onClearItem, onClearFinished }: DocumentUploadQueueProps) {
  if (items.length === 0) return null;
  const hasFinished = items.some((i) => CLEARABLE.has(i.status));

  return (
    <div style={styles.wrap}>
      {items.map((it) => {
        const canRetry = it.status === 'error' || it.status === 'cancelled';
        const canCancel = CANCELABLE.has(it.status);
        const canClear = CLEARABLE.has(it.status);
        const showProgress = PROGRESS_STATUSES.has(it.status);
        return (
          <div key={it.clientId} style={styles.item}>
            <div style={styles.main}>
              <div style={styles.nameRow}>
                <span style={styles.name} title={it.fileName}>{it.fileName}</span>
                <span style={styles.size}>{formatFileSize(it.fileSize)}</span>
              </div>
              <div style={styles.metaRow}>
                <span style={{ ...styles.status, color: statusColor(it.status) }}>● {STATUS_LABELS[it.status]}</span>
                {it.status === 'error' && it.error && <span style={styles.errText}>{it.error}</span>}
              </div>
              {showProgress && (
                <div style={styles.barTrack}>
                  <div style={{ ...styles.barFill, width: `${Math.round(it.progress * 100)}%` }} />
                </div>
              )}
            </div>
            <div style={styles.controls}>
              {canRetry && (
                <button type="button" style={styles.retryBtn} onClick={() => onRetry(it.clientId)}>Повторить</button>
              )}
              {canCancel && (
                <button type="button" style={styles.cancelBtn} onClick={() => onCancel(it.clientId)}>Отменить</button>
              )}
              {canClear && (
                <button type="button" style={styles.clearBtn} onClick={() => onClearItem(it.clientId)} title="Убрать из очереди">✕</button>
              )}
            </div>
          </div>
        );
      })}

      {hasFinished && (
        <div style={styles.footer}>
          <button type="button" style={styles.clearAllBtn} onClick={onClearFinished}>Очистить завершённые</button>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: { display: 'flex', flexDirection: 'column', gap: 8 },
  item: {
    display: 'flex', alignItems: 'flex-start', gap: 10,
    padding: '10px 12px', background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`, borderRadius: 8,
  },
  main: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 },
  nameRow: { display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 },
  name: {
    fontSize: 13, color: theme.text.primary, fontWeight: 500,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const, flex: 1, minWidth: 0,
  },
  size: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, flexShrink: 0 },
  metaRow: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const },
  status: { fontFamily: theme.font.mono, fontSize: 10, flexShrink: 0 },
  errText: { fontFamily: theme.font.mono, fontSize: 10, color: theme.accent.red },
  barTrack: { height: 4, borderRadius: 2, background: theme.bg.input, overflow: 'hidden', marginTop: 2 },
  barFill: { height: '100%', background: theme.accent.amber, transition: 'width 0.18s ease', borderRadius: 2 },
  controls: { display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 },
  retryBtn: {
    padding: '5px 10px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  cancelBtn: {
    padding: '5px 10px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 6, color: theme.text.secondary, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  clearBtn: {
    padding: '5px 9px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 6, color: theme.text.muted, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
  },
  footer: { display: 'flex', justifyContent: 'flex-end' },
  clearAllBtn: {
    padding: '4px 10px', background: 'transparent', border: 'none',
    color: theme.text.muted, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono,
    textDecoration: 'underline',
  },
};
