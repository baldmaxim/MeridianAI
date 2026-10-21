import type { BatchJob } from '../../api/batch';
import { BatchStatusBadge } from './BatchStatusBadge';
import styles from './BatchJobList.module.css';
import { cx } from '../../utils/cx';

interface Props {
  jobs: BatchJob[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function BatchJobList({ jobs, selectedId, onSelect, onDelete }: Props) {
  if (jobs.length === 0) {
    return (
      <div className={styles.empty}>
        Нет задач. Загрузите аудиофайл выше.
      </div>
    );
  }

  return (
    <div className={styles.list}>
      {jobs.map((job) => (
        <div
          key={job.id}
          onClick={() => onSelect(job.id)}
          className={cx(styles.item, selectedId === job.id && styles.itemSelected)}
        >
          <div className={styles.info}>
            <div className={styles.fileName}>
              {job.original_filename}
            </div>
            <div className={styles.fileMeta}>
              {formatSize(job.original_size)}
              {job.compressed_size != null && (
                <span className={styles.compressed}>
                  {' '}{'\u2192'} {formatSize(job.compressed_size)}
                </span>
              )}
              <span className={styles.date}>{formatDate(job.created_at)}</span>
            </div>
          </div>
          <BatchStatusBadge status={job.status} />
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(job.id);
            }}
            className={styles.deleteBtn}
            title="Удалить"
          >
            {'\u2715'}
          </button>
        </div>
      ))}
    </div>
  );
}
