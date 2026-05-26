import { useState, useRef } from 'react';
import { uploadDocument } from '../../api/documents';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';

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
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка загрузки');
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
    <div style={styles.container}>
      {/* Drop zone */}
      <div
        style={{
          ...styles.dropZone,
          borderColor: dragOver ? theme.accent.amber : 'rgba(255,255,255,0.08)',
          background: dragOver ? 'rgba(245,166,35,0.04)' : theme.bg.tertiary,
        }}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <div style={styles.dropIcon}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="3" width="16" height="18" rx="2" stroke={theme.text.muted} strokeWidth="1.5"/>
            <path d="M8 13h8M8 17h5" stroke={theme.text.muted} strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </div>
        <div>
          <div style={styles.dropTitle}>Перетащите файл или нажмите для выбора</div>
          <div style={styles.dropSub}>PDF, MD — AI использует содержимое для анализа и подсказок</div>
        </div>
      </div>
      <input ref={fileRef} type="file" accept=".pdf,.md" style={{ display: 'none' }} onChange={handleUpload} />

      {/* Controls row */}
      <div style={styles.controls}>
        <select value={docType} onChange={(e) => setDocType(e.target.value)} style={styles.select}>
          {DOC_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <button onClick={() => fileRef.current?.click()} disabled={uploading} style={styles.uploadBtn}>
          {uploading ? 'Загрузка...' : '+ Загрузить'}
        </button>
      </div>

      {error && <div style={styles.error}>{error}</div>}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', gap: 12 },
  dropZone: {
    display: 'flex',
    alignItems: 'center',
    gap: 14,
    padding: '18px 20px',
    border: '1px dashed rgba(255,255,255,0.08)',
    borderRadius: 8,
    cursor: 'pointer',
    transition: 'border-color 0.2s, background 0.2s',
  },
  dropIcon: {
    width: 40,
    height: 40,
    borderRadius: 8,
    background: theme.bg.elevated,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  dropTitle: {
    color: theme.text.primary,
    fontSize: 13,
    fontWeight: 500,
    fontFamily: theme.font.body,
  },
  dropSub: {
    color: theme.text.muted,
    fontSize: 11,
    fontFamily: theme.font.body,
    marginTop: 2,
  },
  controls: {
    display: 'flex',
    gap: 8,
    justifyContent: 'flex-end',
    alignItems: 'center',
  },
  select: {
    padding: '8px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 12,
    fontFamily: theme.font.body,
  },
  uploadBtn: {
    padding: '8px 18px',
    background: theme.accent.amber,
    border: 'none',
    borderRadius: 7,
    color: '#080A0F',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: theme.font.body,
  },
  error: { color: theme.accent.red, fontSize: 12 },
};
