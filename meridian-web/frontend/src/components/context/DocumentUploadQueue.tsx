import { formatFileSize } from '../../lib/documentFiles';
import type { DocumentUploadQueueItem, DocumentUploadQueueStatus } from '../../hooks/useDocumentUploadQueue';
import styles from './DocumentUploadQueue.module.css';

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

function statusClass(s: DocumentUploadQueueStatus): string {
  if (s === 'done') return styles.statusDone;
  if (s === 'error') return styles.statusError;
  if (s === 'cancelled') return styles.statusCancelled;
  if (s === 'queued') return styles.statusQueued;
  return styles.statusActive;
}

export function DocumentUploadQueue({ items, onRetry, onCancel, onClearItem, onClearFinished }: DocumentUploadQueueProps) {
  if (items.length === 0) return null;
  const hasFinished = items.some((i) => CLEARABLE.has(i.status));

  return (
    <div className={styles.wrap}>
      {items.map((it) => {
        const canRetry = it.status === 'error' || it.status === 'cancelled';
        const canCancel = CANCELABLE.has(it.status);
        const canClear = CLEARABLE.has(it.status);
        const showProgress = PROGRESS_STATUSES.has(it.status);
        return (
          <div key={it.clientId} className={styles.item}>
            <div className={styles.main}>
              <div className={styles.nameRow}>
                <span className={styles.name} title={it.fileName}>{it.fileName}</span>
                <span className={styles.size}>{formatFileSize(it.fileSize)}</span>
              </div>
              <div className={styles.metaRow}>
                <span className={`${styles.status} ${statusClass(it.status)}`}>● {STATUS_LABELS[it.status]}</span>
                {it.status === 'error' && it.error && <span className={styles.errText}>{it.error}</span>}
              </div>
              {showProgress && (
                <div className={styles.barTrack}>
                  <div className={styles.barFill} style={{ transform: `scaleX(${Math.min(1, Math.max(0, it.progress))})` }} />
                </div>
              )}
            </div>
            <div className={styles.controls}>
              {canRetry && (
                <button type="button" className={styles.retryBtn} onClick={() => onRetry(it.clientId)}>Повторить</button>
              )}
              {canCancel && (
                <button type="button" className={styles.cancelBtn} onClick={() => onCancel(it.clientId)}>Отменить</button>
              )}
              {canClear && (
                <button type="button" className={styles.clearBtn} onClick={() => onClearItem(it.clientId)} title="Убрать из очереди">✕</button>
              )}
            </div>
          </div>
        );
      })}

      {hasFinished && (
        <div className={styles.footer}>
          <button type="button" className={styles.clearAllBtn} onClick={onClearFinished}>Очистить завершённые</button>
        </div>
      )}
    </div>
  );
}
