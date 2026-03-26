import type { BatchJob } from '../../api/batch';
import { BatchStatusBadge } from './BatchStatusBadge';
import { theme } from '../../styles/theme';

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
      <div
        style={{
          textAlign: 'center',
          padding: '40px 20px',
          color: theme.text.muted,
          fontFamily: theme.font.body,
          fontSize: 13,
        }}
      >
        Нет задач. Загрузите аудиофайл выше.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {jobs.map((job) => (
        <div
          key={job.id}
          onClick={() => onSelect(job.id)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '10px 14px',
            borderRadius: 8,
            cursor: 'pointer',
            background: selectedId === job.id ? theme.bg.elevated : theme.bg.card,
            border: `1px solid ${selectedId === job.id ? theme.border.amber : theme.border.default}`,
            transition: 'all 0.15s',
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontFamily: theme.font.body,
                fontSize: 12,
                fontWeight: 500,
                color: theme.text.primary,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {job.original_filename}
            </div>
            <div
              style={{
                fontFamily: theme.font.mono,
                fontSize: 10,
                color: theme.text.muted,
                marginTop: 2,
              }}
            >
              {formatSize(job.original_size)}
              {job.compressed_size != null && (
                <span style={{ color: theme.accent.green }}>
                  {' '}{'\u2192'} {formatSize(job.compressed_size)}
                </span>
              )}
              <span style={{ marginLeft: 8 }}>{formatDate(job.created_at)}</span>
            </div>
          </div>
          <BatchStatusBadge status={job.status} />
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(job.id);
            }}
            style={{
              background: 'transparent',
              border: 'none',
              color: theme.text.muted,
              cursor: 'pointer',
              fontSize: 14,
              padding: '2px 6px',
              borderRadius: 4,
              lineHeight: 1,
            }}
            title="Удалить"
          >
            {'\u2715'}
          </button>
        </div>
      ))}
    </div>
  );
}
