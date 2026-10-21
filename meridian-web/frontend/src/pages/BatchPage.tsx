import { useState } from 'react';
import { BatchUpload } from '../components/batch/BatchUpload';
import { BatchJobList } from '../components/batch/BatchJobList';
import { BatchJobDetail } from '../components/batch/BatchJobDetail';
import { useBatchJobs, useUploadBatch, useDeleteBatchJob, useCreateBatchFromStash } from '../hooks/queries/batch';
import { useStashFiles } from '../hooks/queries/stash';
import { Modal } from '../components/common/Modal';
import { errorDetail } from '../lib/errorDetail';
import { getFileExtension, formatFileSize } from '../lib/documentFiles';
import styles from './BatchPage.module.css';
import { cx } from '../utils/cx';

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
    } catch (e) {
      alert(errorDetail(e) || 'Ошибка загрузки');
    }
  };

  const handlePickStash = async (id: number) => {
    try {
      const job = await fromStashMut.mutateAsync(id);
      setSelectedId(job.id);
      setPickerOpen(false);
    } catch (e) {
      alert(errorDetail(e) || 'Ошибка');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteMut.mutateAsync(id);
      if (selectedId === id) setSelectedId(null);
    } catch { /* ignore */ }
  };

  return (
    <div className={styles.container}>
      {/* Left panel: upload + list */}
      <div className={cx(styles.left, !!selectedId && styles.leftCompact)}>
        <div className={styles.topBar}>
          <button onClick={onBack} className={styles.backBtn}>{'\u2190'} Назад</button>
          <h2 className={styles.title}>Оффлайн распознавание</h2>
        </div>
        <BatchUpload onUpload={handleUpload} uploading={uploadMut.isPending} />
        <button
          onClick={() => setPickerOpen(true)}
          disabled={fromStashMut.isPending}
          className={styles.pickBtn}
        >
          {'📁'} Выбрать из «Файлов»
        </button>
        <div className={styles.jobs}>
          <BatchJobList
            jobs={jobs}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDelete={handleDelete}
          />
        </div>
      </div>

      {/* Right panel: detail */}
      <div className={styles.right}>
        {selectedId ? (
          <BatchJobDetail jobId={selectedId} />
        ) : (
          <div className={styles.placeholder}>
            Выберите задачу из списка
          </div>
        )}
      </div>

      <Modal open={pickerOpen} onClose={() => setPickerOpen(false)} maxWidth={480}>
        <div className={styles.modalTitle}>Аудио из «Файлов»</div>
        {audioStash.length === 0 ? (
          <div className={styles.modalEmpty}>
            Нет аудиофайлов в «Файлах». Загрузите их на странице «Файлы» — форматы: MP3, WAV, M4A, OGG, FLAC, OPUS, WEBM.
          </div>
        ) : (
          audioStash.map((f) => (
            <button
              key={f.id}
              onClick={() => handlePickStash(f.id)}
              disabled={fromStashMut.isPending}
              className={styles.stashRow}
            >
              <span className={styles.stashName}>{f.original_name}</span>
              <span className={styles.stashMeta}>{f.size != null ? formatFileSize(f.size) : ''}</span>
            </button>
          ))
        )}
      </Modal>
    </div>
  );
}
