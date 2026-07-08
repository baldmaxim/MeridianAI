import { useState, useRef, useCallback } from 'react';
import { useStashFiles, useUploadStash, useDeleteStash } from '../hooks/queries/stash';
import type { StashFile } from '../api/stash';
import { downloadStashFile } from '../api/stash';
import { formatFileSize } from '../lib/documentFiles';
import { theme } from '../styles/theme';

interface Props {
  onBack: () => void;
}

function expiryLabel(expires_at: string | null): string {
  if (!expires_at) return '';
  const ms = new Date(expires_at).getTime() - Date.now();
  if (ms <= 0) return 'истёк';
  const days = Math.ceil(ms / 86_400_000);
  if (days <= 1) return 'удалится сегодня';
  return `удалится через ${days} дн.`;
}

export function StashPage({ onBack }: Props) {
  const { data: files = [] } = useStashFiles();
  const uploadMut = useUploadStash();
  const deleteMut = useDeleteStash();

  const [dragOver, setDragOver] = useState(false);
  const [pct, setPct] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFiles = useCallback(
    async (list: FileList | File[]) => {
      const arr = Array.from(list);
      for (const file of arr) {
        try {
          setPct(0);
          await uploadMut.mutateAsync({ file, onProgress: (f) => setPct(Math.round(f * 100)) });
        } catch (e: any) {
          alert(e?.response?.data?.detail || e?.message || 'Ошибка загрузки');
        }
      }
      setPct(0);
    },
    [uploadMut]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files?.length) uploadFiles(e.dataTransfer.files);
    },
    [uploadFiles]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files?.length) uploadFiles(e.target.files);
      e.target.value = '';
    },
    [uploadFiles]
  );

  const handleDownload = async (id: number) => {
    setBusyId(id);
    try {
      await downloadStashFile(id);
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Не удалось скачать');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (f: StashFile) => {
    if (!window.confirm(`Удалить «${f.original_name}»?`)) return;
    try {
      await deleteMut.mutateAsync(f.id);
    } catch { /* список обновится сам */ }
  };

  const uploading = uploadMut.isPending;

  return (
    <div className="stash-page" style={styles.container}>
      <div style={styles.topBar}>
        <button onClick={onBack} style={styles.backBtn}>{'←'} Назад</button>
        <h2 style={styles.title}>Файлы</h2>
      </div>
      <p style={styles.subtitle}>
        Личное временное хранилище. Загрузите с одного устройства — скачайте с другого.
        Файлы автоматически удаляются по сроку; можно удалить вручную.
      </p>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !uploading && inputRef.current?.click()}
        style={{
          border: `2px dashed ${dragOver ? theme.accent.amber : theme.border.default}`,
          borderRadius: 12,
          padding: '32px 24px',
          textAlign: 'center',
          cursor: uploading ? 'wait' : 'pointer',
          background: dragOver ? theme.accent.amberGlow : theme.bg.card,
          transition: 'all 0.2s',
        }}
      >
        <input ref={inputRef} type="file" multiple onChange={handleChange} style={{ display: 'none' }} />
        <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.6 }}>{uploading ? '⏳' : '📁'}</div>
        <div style={{ fontFamily: theme.font.body, fontSize: 13, color: theme.text.secondary, marginBottom: 4 }}>
          {uploading ? `Загрузка… ${pct}%` : 'Перетащите файлы или нажмите для выбора'}
        </div>
        <div style={{ fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted }}>
          Любой тип файла
        </div>
      </div>

      <div style={styles.list}>
        {files.length === 0 && (
          <div style={styles.empty}>Пока нет файлов</div>
        )}
        {files.map((f) => (
          <div key={f.id} style={styles.row}>
            <div style={styles.rowMain}>
              <div style={styles.name} title={f.original_name}>{f.original_name}</div>
              <div style={styles.meta}>
                {f.size != null ? formatFileSize(f.size) : '—'}
                {f.expires_at && <span style={styles.expiry}> · {expiryLabel(f.expires_at)}</span>}
              </div>
            </div>
            <div style={styles.actions}>
              <button
                onClick={() => handleDownload(f.id)}
                disabled={busyId === f.id}
                style={styles.downloadBtn}
              >
                {busyId === f.id ? '…' : 'Скачать'}
              </button>
              <button onClick={() => handleDelete(f)} style={styles.deleteBtn} aria-label="Удалить" title="Удалить">
                {'✕'}
              </button>
            </div>
          </div>
        ))}
      </div>

      <style>{`
        @media (max-width: 767px) {
          .stash-page { padding: 12px !important; }
        }
      `}</style>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: 24,
    maxWidth: 760,
    width: '100%',
    margin: '0 auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  backBtn: {
    background: 'transparent',
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 5,
    color: theme.accent.amber,
    cursor: 'pointer',
    padding: '4px 10px',
    fontFamily: theme.font.mono,
    fontSize: 10,
    letterSpacing: '0.06em',
  },
  title: {
    fontFamily: theme.font.heading,
    fontSize: 16,
    fontWeight: 800,
    color: theme.text.primary,
    letterSpacing: '0.1em',
    margin: 0,
  },
  subtitle: {
    fontFamily: theme.font.body,
    fontSize: 12,
    color: theme.text.secondary,
    margin: 0,
    lineHeight: 1.5,
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    marginTop: 4,
  },
  empty: {
    textAlign: 'center',
    color: theme.text.muted,
    fontFamily: theme.font.body,
    fontSize: 13,
    padding: '24px 0',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '10px 14px',
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
  },
  rowMain: {
    flex: 1,
    minWidth: 0,
  },
  name: {
    fontFamily: theme.font.body,
    fontSize: 13,
    color: theme.text.primary,
    fontWeight: 600,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  meta: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
    marginTop: 2,
  },
  expiry: {
    color: theme.text.secondary,
  },
  actions: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexShrink: 0,
  },
  downloadBtn: {
    padding: '5px 12px',
    background: 'transparent',
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 5,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontFamily: theme.font.mono,
    fontSize: 10,
    letterSpacing: '0.06em',
  },
  deleteBtn: {
    width: 28,
    height: 28,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: theme.accent.redDim,
    border: `1px solid ${theme.accent.red}`,
    borderRadius: 5,
    color: theme.accent.red,
    cursor: 'pointer',
    fontSize: 12,
    lineHeight: 1,
  },
};
