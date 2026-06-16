import { useState, useEffect, useCallback } from 'react';
import type { BatchJob } from '../api/batch';
import { uploadBatchAudio, getBatchJobs, deleteBatchJob } from '../api/batch';
import { BatchUpload } from '../components/batch/BatchUpload';
import { BatchJobList } from '../components/batch/BatchJobList';
import { BatchJobDetail } from '../components/batch/BatchJobDetail';
import { theme } from '../styles/theme';

interface Props {
  onBack: () => void;
}

export function BatchPage({ onBack }: Props) {
  const [jobs, setJobs] = useState<BatchJob[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);

  const loadJobs = useCallback(async () => {
    try {
      const data = await getBatchJobs();
      setJobs(data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadJobs();
    const timer = setInterval(loadJobs, 5000);
    return () => clearInterval(timer);
  }, [loadJobs]);

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true);
    try {
      const job = await uploadBatchAudio(file);
      setSelectedId(job.id);
      await loadJobs();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Ошибка загрузки');
    } finally {
      setUploading(false);
    }
  }, [loadJobs]);

  const handleDelete = useCallback(async (id: number) => {
    try {
      await deleteBatchJob(id);
      if (selectedId === id) setSelectedId(null);
      await loadJobs();
    } catch { /* ignore */ }
  }, [selectedId, loadJobs]);

  return (
    <div className="batch-page" style={styles.container}>
      {/* Left panel: upload + list */}
      <div className="batch-left" style={styles.left}>
        <div style={styles.topBar}>
          <button onClick={onBack} style={styles.backBtn}>{'\u2190'} Назад</button>
          <h2 style={styles.title}>Оффлайн распознавание</h2>
        </div>
        <BatchUpload onUpload={handleUpload} uploading={uploading} />
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
    overflowY: 'auto',
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
};
