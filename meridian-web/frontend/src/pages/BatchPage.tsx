import { useState } from 'react';
import { BatchUpload } from '../components/batch/BatchUpload';
import { BatchJobList } from '../components/batch/BatchJobList';
import { BatchJobDetail } from '../components/batch/BatchJobDetail';
import { useBatchJobs, useUploadBatch, useDeleteBatchJob, useCreateBatchFromStash } from '../hooks/queries/batch';
import { useStashFiles } from '../hooks/queries/stash';
import { Modal } from '../components/common/Modal';
import { getFileExtension, formatFileSize } from '../lib/documentFiles';
import { theme } from '../styles/theme';

const AUDIO_EXT = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.opus', '.webm'];

interface Props {
  onBack: () => void;
}

export function BatchPage({ onBack }: Props) {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data: jobs = [] } = useBatchJobs(); // polling 5с внутри хука
  const uploadMut = useUploadBatch();
  const deleteMut = useDeleteBatchJob();
  const fromStashMut = useCreateBatchFromStash();
  const { data: stashFiles = [] } = useStashFiles();
  const [pickerOpen, setPickerOpen] = useState(false);

  const audioStash = stashFiles.filter((f) => AUDIO_EXT.includes(getFileExtension(f.original_name)));

  const handleUpload = async (file: File) => {
    try {
      const job = await uploadMut.mutateAsync(file);
      setSelectedId(job.id);
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Ошибка загрузки');
    }
  };

  const handlePickStash = async (id: number) => {
    try {
      const job = await fromStashMut.mutateAsync(id);
      setSelectedId(job.id);
      setPickerOpen(false);
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Ошибка');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteMut.mutateAsync(id);
      if (selectedId === id) setSelectedId(null);
    } catch { /* ignore */ }
  };

  return (
    <div className="batch-page" style={styles.container}>
      {/* Left panel: upload + list */}
      <div className="batch-left" style={styles.left}>
        <div style={styles.topBar}>
          <button onClick={onBack} style={styles.backBtn}>{'\u2190'} Назад</button>
          <h2 style={styles.title}>Оффлайн распознавание</h2>
        </div>
        <BatchUpload onUpload={handleUpload} uploading={uploadMut.isPending} />
        <button
          onClick={() => setPickerOpen(true)}
          disabled={fromStashMut.isPending}
          style={styles.pickBtn}
        >
          {'📁'} Выбрать из «Файлов»
        </button>
        <div style={{ marginTop: 16, flex: 1, overflowY: 'auto' }}>
          <BatchJobList
            jobs={jobs}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDelete={handleDelete}
          />
        </div>
      </div>

      {/* Right panel: detail */}
      <div className="batch-right" style={styles.right}>
        {selectedId ? (
          <BatchJobDetail jobId={selectedId} />
        ) : (
          <div style={styles.placeholder}>
            Выберите задачу из списка
          </div>
        )}
      </div>

      <Modal open={pickerOpen} onClose={() => setPickerOpen(false)} maxWidth={480}>
        <div style={styles.modalTitle}>Аудио из «Файлов»</div>
        {audioStash.length === 0 ? (
          <div style={styles.modalEmpty}>
            Нет аудиофайлов в «Файлах». Загрузите их на странице «Файлы» — форматы: MP3, WAV, M4A, OGG, FLAC, OPUS, WEBM.
          </div>
        ) : (
          audioStash.map((f) => (
            <button
              key={f.id}
              onClick={() => handlePickStash(f.id)}
              disabled={fromStashMut.isPending}
              style={styles.stashRow}
            >
              <span style={styles.stashName}>{f.original_name}</span>
              <span style={styles.stashMeta}>{f.size != null ? formatFileSize(f.size) : ''}</span>
            </button>
          ))
        )}
      </Modal>

      <style>{`
        .batch-page {
          display: flex !important;
          flex-direction: row !important;
        }
        @media (max-width: 767px) {
          .batch-page {
            flex-direction: column !important;
          }
          .batch-left {
            max-height: ${selectedId ? '45vh' : '100%'} !important;
            border-right: none !important;
            border-bottom: 1px solid rgba(255,255,255,0.06) !important;
          }
          .batch-right {
            flex: 1 !important;
            min-height: 0 !important;
          }
        }
      `}</style>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flex: 1,
    overflow: 'hidden',
  },
  left: {
    width: 420,
    minWidth: 320,
    maxWidth: 500,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    padding: 16,
    borderRight: `1px solid ${theme.border.default}`,
    overflowY: 'auto',
  },
  right: {
    flex: 1,
    padding: 20,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    minHeight: 0,
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 4,
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
  placeholder: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: theme.text.muted,
    fontFamily: theme.font.body,
    fontSize: 13,
  },
  pickBtn: {
    width: '100%',
    padding: '9px 12px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontFamily: theme.font.mono,
    fontSize: 11,
    letterSpacing: '0.04em',
  },
  modalTitle: {
    fontFamily: theme.font.heading,
    fontSize: 14,
    fontWeight: 800,
    color: theme.text.primary,
    letterSpacing: '0.08em',
  },
  modalEmpty: {
    color: theme.text.secondary,
    fontFamily: theme.font.body,
    fontSize: 12,
    lineHeight: 1.5,
  },
  stashRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    width: '100%',
    padding: '10px 12px',
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
    cursor: 'pointer',
    textAlign: 'left',
  },
  stashName: {
    fontFamily: theme.font.body,
    fontSize: 13,
    color: theme.text.primary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    minWidth: 0,
  },
  stashMeta: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
    flexShrink: 0,
  },
};
