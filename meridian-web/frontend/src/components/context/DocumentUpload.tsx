import { useState, useRef } from 'react';
import { uploadDocument } from '../../api/documents';
import { useMeetingStore } from '../../store/meetingStore';
import { isAxiosError } from 'axios';
import { Select } from '../common';
import styles from './DocumentUpload.module.css';

const DOC_TYPES = [
  { value: 'contract', label: 'Контракт' },
  { value: 'bor', label: 'ВОР' },
  { value: 'estimate', label: 'Смета' },
  { value: 'specification', label: 'Спецификация' },
  { value: 'other', label: 'Другое' },
];

export function DocumentUpload() {
  const [docType, setDocType] = useState('contract');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const addDocument = useMeetingStore((s) => s.addDocument);

  const doUpload = async (file: File) => {
    setUploading(true);
    setError('');
    try {
      const doc = await uploadDocument(file, docType);
      addDocument(doc);
      if (fileRef.current) fileRef.current.value = '';
    } catch (err) {
      const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
      setError(typeof detail === 'string' && detail ? detail : 'Ошибка загрузки');
    } finally {
      setUploading(false);
    }
  };

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    await doUpload(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) doUpload(file);
  };

  return (
    <div className={styles.container}>
      {/* Drop zone */}
      <div
        className={`${styles.dropZone} ${dragOver ? styles.dropZoneActive : ''}`}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <div className={styles.dropIcon}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="3" width="16" height="18" rx="2" stroke="var(--text-muted)" strokeWidth="1.5"/>
            <path d="M8 13h8M8 17h5" stroke="var(--text-muted)" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </div>
        <div>
          <div className={styles.dropTitle}>Перетащите файл или нажмите для выбора</div>
          <div className={styles.dropSub}>PDF, MD — AI использует содержимое для анализа и подсказок</div>
        </div>
      </div>
      <input ref={fileRef} type="file" accept=".pdf,.md" className={styles.hidden} onChange={handleUpload} />

      {/* Controls row */}
      <div className={styles.controls}>
        <Select
          value={docType}
          onChange={setDocType}
          options={DOC_TYPES}
          triggerClassName={styles.select}
          ariaLabel="Тип документа"
        />
        <button onClick={() => fileRef.current?.click()} disabled={uploading} className={styles.uploadBtn}>
          {uploading ? 'Загрузка...' : '+ Загрузить'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}
    </div>
  );
}
