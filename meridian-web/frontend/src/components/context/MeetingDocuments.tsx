import { useState, useEffect, useRef, useCallback } from 'react';
import { theme } from '../../styles/theme';
import { listDocumentRecords } from '../../api/documents';
import { listMeetingDocuments, attachMeetingDocument, patchMeetingDocument, detachMeetingDocument } from '../../api/meetingDocuments';
import { apiErrorMessage } from '../../lib/apiError';
import type { MeetingDocument, DocumentRecord } from '../../types';
import { ContextSourceCard } from './ContextSourceCard';
import { documentToContextSourceViewModel, type ContextSourceSectionSummary } from './contextSourceModel';
import { useDocumentUploadQueue } from '../../hooks/useDocumentUploadQueue';
import { DocumentUploadQueue } from './DocumentUploadQueue';
import { Select } from '../common';

interface Props {
  meetingId: number | null;
  customerId?: number | null;
  objectId?: number | null;
  ensureMeetingId?: () => Promise<number | null>;
  onSummaryChange?: (summary: ContextSourceSectionSummary) => void;
  onUploadActivityChange?: (activeCount: number) => void;
}

// Из drop-события берём только файлы, игнорируя папки (webkitGetAsEntry).
function extractFiles(dt: DataTransfer): File[] {
  if (dt.items && dt.items.length) {
    const out: File[] = [];
    for (let i = 0; i < dt.items.length; i++) {
      const item = dt.items[i];
      if (item.kind !== 'file') continue;
      const entry = item.webkitGetAsEntry?.();
      if (entry && entry.isDirectory) continue;
      const f = item.getAsFile();
      if (f) out.push(f);
    }
    return out;
  }
  return Array.from(dt.files);
}

export function MeetingDocuments({ meetingId, customerId, objectId, ensureMeetingId, onSummaryChange, onUploadActivityChange }: Props) {
  const [docs, setDocs] = useState<MeetingDocument[]>([]);
  const [error, setError] = useState('');
  const [existing, setExisting] = useState<DocumentRecord[]>([]);
  const [pickId, setPickId] = useState<number | ''>('');
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (meetingId == null) return;
    try {
      setDocs(await listMeetingDocuments(meetingId));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось загрузить документы'));
    }
  }, [meetingId]);

  useEffect(() => { load(); }, [load]);

  // Если ensureMeetingId не передан — fallback: вернуть текущий meetingId либо null.
  const ensureMeetingIdFn = useCallback(async (): Promise<number | null> => {
    if (ensureMeetingId) return ensureMeetingId();
    return meetingId;
  }, [ensureMeetingId, meetingId]);

  const queue = useDocumentUploadQueue({
    customerId,
    objectId,
    ensureMeetingId: ensureMeetingIdFn,
    onAttached: load,
    maxParallel: 1,
  });

  // Сводка для корзины контекста. Колбэк в ref → effect зависит только от docs.
  const onSummaryChangeRef = useRef(onSummaryChange);
  onSummaryChangeRef.current = onSummaryChange;
  useEffect(() => {
    if (!onSummaryChangeRef.current) return;
    onSummaryChangeRef.current({
      total: docs.length,
      included: docs.filter((d) => d.included).length,
      ready: docs.filter((d) => d.status === 'ready').length,
      processing: docs.filter((d) => d.status !== 'ready' && d.status !== 'error').length,
      errors: docs.filter((d) => d.status === 'error').length,
    });
  }, [docs]);

  // Активность загрузки → корзине (для чипа «Загрузка: N»).
  const onUploadActivityChangeRef = useRef(onUploadActivityChange);
  onUploadActivityChangeRef.current = onUploadActivityChange;
  useEffect(() => { onUploadActivityChangeRef.current?.(queue.activeCount); }, [queue.activeCount]);

  // поллинг, пока есть документы в обработке
  useEffect(() => {
    const pendingExists = docs.some((d) => d.status !== 'ready' && d.status !== 'error');
    if (!pendingExists || meetingId == null) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [docs, meetingId, load]);

  // существующие документы по объекту (для «выбрать существующий»)
  useEffect(() => {
    if (objectId == null) { setExisting([]); return; }
    listDocumentRecords({ object_id: objectId }).then(setExisting).catch(() => setExisting([]));
  }, [objectId, docs]);

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const files = extractFiles(e.dataTransfer);
    if (files.length) { setError(''); queue.addFiles(files); }
  }

  async function attachExisting() {
    if (pickId === '') return;
    setError('');
    try {
      const id = await ensureMeetingIdFn();
      if (id == null) { setError('Не удалось создать встречу'); return; }
      await attachMeetingDocument(id, Number(pickId));
      setPickId('');
      setDocs(await listMeetingDocuments(id));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось прикрепить документ'));
    }
  }

  async function toggleIncluded(d: MeetingDocument) {
    if (meetingId == null) return;
    try {
      await patchMeetingDocument(meetingId, d.document_id, { included: !d.included });
      await load();
    } catch (e) { setError(apiErrorMessage(e, 'Ошибка')); }
  }

  async function detach(d: MeetingDocument) {
    if (meetingId == null) return;
    if (!confirm(`Открепить «${d.original_name}»?`)) return;
    try {
      await detachMeetingDocument(meetingId, d.document_id);
      await load();
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось открепить')); }
  }

  const attachedIds = new Set(docs.map((d) => d.document_id));
  const available = existing.filter((d) => !attachedIds.has(d.id) && d.status === 'ready');

  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>Документы встречи</span>
        <span style={{ flex: 1 }} />
        <button style={styles.refreshBtn} onClick={load} disabled={meetingId == null}>↻</button>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {/* Загрузка: кнопка + drag-and-drop */}
      <div
        style={{ ...styles.dropZone, ...(dragOver ? styles.dropZoneActive : {}) }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files;
            if (f && f.length) { setError(''); queue.addFiles(Array.from(f)); }
            if (fileRef.current) fileRef.current.value = '';
          }}
        />
        <div style={styles.dropText}>
          {queue.hasActiveUploads
            ? 'Файлы загружаются — можно продолжать настройку встречи'
            : dragOver
              ? 'Отпустите файлы, чтобы добавить в контекст'
              : 'Перетащите файлы сюда или загрузите кнопкой'}
        </div>
        <div style={styles.uploadRow}>
          <button style={styles.uploadBtn} onClick={() => fileRef.current?.click()}>
            + Загрузить документ
          </button>
          <span style={styles.hint}>PDF, DOCX, XLSX, TXT, MD, CSV</span>
        </div>
      </div>

      {/* Очередь загрузки */}
      <DocumentUploadQueue
        items={queue.items}
        onRetry={queue.retryItem}
        onCancel={queue.cancelItem}
        onClearItem={queue.clearItem}
        onClearFinished={queue.clearFinished}
      />

      {/* Выбрать существующий */}
      {available.length > 0 && (
        <div style={styles.pickRow}>
          <Select
            style={styles.select}
            wrapperStyle={{ flex: 1, minWidth: 0 }}
            ariaLabel="Существующий документ"
            value={String(pickId)}
            onChange={(v) => setPickId(v === '' ? '' : Number(v))}
            options={[{ value: '', label: '— выбрать существующий —' },
              ...available.map((d) => ({ value: String(d.id), label: d.original_name }))]}
          />
          <button style={styles.attachBtn} onClick={attachExisting} disabled={pickId === ''}>Прикрепить</button>
        </div>
      )}

      {/* Список */}
      {docs.length === 0 && <div style={styles.empty}>Документы не прикреплены</div>}
      <div style={styles.list}>
        {docs.map((d) => (
          <ContextSourceCard
            key={d.id}
            source={documentToContextSourceViewModel(d)}
            onToggleIncluded={() => toggleIncluded(d)}
            onRemove={() => detach(d)}
          />
        ))}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: { background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 20, display: 'flex', flexDirection: 'column', gap: 12 },
  header: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  title: { fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: theme.text.primary },
  refreshBtn: { width: 28, height: 24, background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.secondary, cursor: 'pointer', fontSize: 13 },
  dropZone: {
    display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center',
    padding: '18px 16px', borderRadius: 10,
    border: `1.5px dashed ${theme.border.default}`, background: theme.bg.tertiary,
    transition: 'border-color 0.18s, background 0.18s', textAlign: 'center' as const,
  },
  dropZoneActive: {
    borderColor: theme.accent.amber, background: theme.accent.amberGlow,
  },
  dropText: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, letterSpacing: '0.04em' },
  uploadRow: { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' as const, justifyContent: 'center' },
  uploadBtn: { padding: '10px 16px', background: theme.accent.amber, border: 'none', borderRadius: 8, color: '#080A0F', cursor: 'pointer', fontSize: 12, fontWeight: 600, fontFamily: theme.font.body },
  hint: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  pickRow: { display: 'flex', gap: 8 },
  select: { flex: 1, padding: '9px 12px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none' },
  attachBtn: { padding: '9px 14px', background: 'transparent', border: `1px solid ${theme.border.amber}`, borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono },
  empty: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 12 },
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
};
