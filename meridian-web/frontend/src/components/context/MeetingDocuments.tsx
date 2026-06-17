import { useState, useEffect, useRef, useCallback } from 'react';
import { theme } from '../../styles/theme';
import { uploadDocumentPresigned, listDocumentRecords } from '../../api/documents';
import { listMeetingDocuments, attachMeetingDocument, patchMeetingDocument, detachMeetingDocument } from '../../api/meetingDocuments';
import { apiErrorMessage } from '../../lib/apiError';
import type { MeetingDocument, DocumentRecord } from '../../types';
import { ContextSourceCard } from './ContextSourceCard';
import { documentToContextSourceViewModel, type ContextSourceSectionSummary } from './contextSourceModel';

interface Props {
  meetingId: number | null;
  customerId?: number | null;
  objectId?: number | null;
  onSummaryChange?: (summary: ContextSourceSectionSummary) => void;
}

const ALLOWED_EXT = ['.pdf', '.docx', '.xlsx', '.txt', '.md', '.csv'];

function isAllowedFile(name: string): boolean {
  const lower = name.toLowerCase();
  return ALLOWED_EXT.some((ext) => lower.endsWith(ext));
}

export function MeetingDocuments({ meetingId, customerId, objectId, onSummaryChange }: Props) {
  const [docs, setDocs] = useState<MeetingDocument[]>([]);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [existing, setExisting] = useState<DocumentRecord[]>([]);
  const [pickId, setPickId] = useState<number | ''>('');
  const [dragOver, setDragOver] = useState(false);
  const [batch, setBatch] = useState<{ idx: number; total: number } | null>(null);
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

  // Сводка для корзины контекста. Колбэк в ref → effect зависит только от docs,
  // что исключает render-loop, даже если родитель передаёт нестабильный колбэк.
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

  async function onFile(file: File) {
    if (meetingId == null) { setError('Сначала создаётся встреча'); return; }
    setError(''); setUploading(true); setProgress(0);
    try {
      const { document_id } = await uploadDocumentPresigned(
        file, { customer_id: customerId ?? null, object_id: objectId ?? null }, setProgress,
      );
      await attachMeetingDocument(meetingId, document_id);
      if (fileRef.current) fileRef.current.value = '';
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Ошибка загрузки документа'));
    } finally {
      setUploading(false); setProgress(0);
    }
  }

  // Последовательная загрузка пачки файлов (кнопка с multiple + drag-and-drop).
  async function uploadMany(files: File[]) {
    if (meetingId == null) { setError('Сначала создаётся встреча'); return; }
    const ok = files.filter((f) => isAllowedFile(f.name));
    const bad = files.filter((f) => !isAllowedFile(f.name));
    if (ok.length === 0) {
      if (bad.length) setError(`Неподдерживаемый формат: ${bad.map((f) => f.name).join(', ')}`);
      return;
    }
    setBatch({ idx: 0, total: ok.length });
    for (let i = 0; i < ok.length; i++) {
      setBatch({ idx: i + 1, total: ok.length });
      await onFile(ok[i]);
    }
    setBatch(null);
    if (bad.length) setError((prev) => prev || `Не загружены (формат): ${bad.map((f) => f.name).join(', ')}`);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) uploadMany(files);
  }

  async function attachExisting() {
    if (meetingId == null || pickId === '') return;
    setError('');
    try {
      await attachMeetingDocument(meetingId, Number(pickId));
      setPickId('');
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось прикрепить документ'));
    }
  }

  async function toggleIncluded(d: MeetingDocument) {
    try {
      await patchMeetingDocument(meetingId!, d.document_id, { included: !d.included });
      await load();
    } catch (e) { setError(apiErrorMessage(e, 'Ошибка')); }
  }

  async function detach(d: MeetingDocument) {
    if (!confirm(`Открепить «${d.original_name}»?`)) return;
    try {
      await detachMeetingDocument(meetingId!, d.document_id);
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
        onDragOver={(e) => { e.preventDefault(); if (meetingId != null && !uploading) setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
          style={{ display: 'none' }}
          onChange={(e) => { const f = e.target.files; if (f && f.length) uploadMany(Array.from(f)); }}
        />
        <div style={styles.dropText}>
          {batch
            ? `Загрузка ${batch.idx}/${batch.total}… ${Math.round(progress * 100)}%`
            : uploading
              ? `Загрузка… ${Math.round(progress * 100)}%`
              : meetingId == null
                ? 'Сначала создаётся встреча'
                : 'Перетащите файлы сюда'}
        </div>
        <div style={styles.uploadRow}>
          <button
            style={styles.uploadBtn}
            onClick={() => fileRef.current?.click()}
            disabled={uploading || meetingId == null}
          >
            + Загрузить документ
          </button>
          <span style={styles.hint}>PDF, DOCX, XLSX, TXT, MD, CSV</span>
        </div>
      </div>

      {/* Выбрать существующий */}
      {available.length > 0 && (
        <div style={styles.pickRow}>
          <select style={styles.select} value={pickId} onChange={(e) => setPickId(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">— выбрать существующий —</option>
            {available.map((d) => <option key={d.id} value={d.id}>{d.original_name}</option>)}
          </select>
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
  item: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`, borderRadius: 8 },
  itemMain: { flex: 1, minWidth: 0 },
  itemName: { fontSize: 13, color: theme.text.primary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  itemMeta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, marginTop: 2 },
  toggleOn: { padding: '5px 10px', background: 'rgba(46,229,157,0.1)', border: '1px solid rgba(46,229,157,0.25)', borderRadius: 6, color: theme.accent.green, cursor: 'pointer', fontSize: 9, fontFamily: theme.font.mono },
  toggleOff: { padding: '5px 10px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.muted, cursor: 'pointer', fontSize: 9, fontFamily: theme.font.mono },
  detachBtn: { padding: '5px 9px', background: 'transparent', border: `1px solid ${theme.accent.red}`, borderRadius: 6, color: theme.accent.red, cursor: 'pointer', fontSize: 10, fontFamily: theme.font.mono },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
};
