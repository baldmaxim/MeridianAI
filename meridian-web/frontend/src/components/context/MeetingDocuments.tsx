import { useState, useEffect, useRef, useCallback } from 'react';
import { theme } from '../../styles/theme';
import { uploadDocumentPresigned, listDocumentRecords } from '../../api/documents';
import { listMeetingDocuments, attachMeetingDocument, patchMeetingDocument, detachMeetingDocument } from '../../api/meetingDocuments';
import { apiErrorMessage } from '../../lib/apiError';
import type { MeetingDocument, DocumentRecord, DocumentStatus } from '../../types';

interface Props {
  meetingId: number | null;
  customerId?: number | null;
  objectId?: number | null;
}

const STATUS_LABELS: Record<DocumentStatus, string> = {
  pending: 'ожидание',
  uploaded: 'загружен',
  processing: 'обработка…',
  ready: 'готов',
  error: 'ошибка',
};

function statusColor(s: DocumentStatus): string {
  if (s === 'ready') return theme.accent.green;
  if (s === 'error') return theme.accent.red;
  if (s === 'processing') return theme.accent.amber;
  return theme.text.muted;
}

export function MeetingDocuments({ meetingId, customerId, objectId }: Props) {
  const [docs, setDocs] = useState<MeetingDocument[]>([]);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [existing, setExisting] = useState<DocumentRecord[]>([]);
  const [pickId, setPickId] = useState<number | ''>('');
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

      {/* Загрузка */}
      <div style={styles.uploadRow}>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
          style={{ display: 'none' }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }}
        />
        <button
          style={styles.uploadBtn}
          onClick={() => fileRef.current?.click()}
          disabled={uploading || meetingId == null}
        >
          {uploading ? `Загрузка… ${Math.round(progress * 100)}%` : '+ Загрузить документ'}
        </button>
        <span style={styles.hint}>PDF, DOCX, XLSX, TXT, MD, CSV</span>
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
          <div key={d.id} style={{ ...styles.item, opacity: d.included ? 1 : 0.5 }}>
            <div style={styles.itemMain}>
              <div style={styles.itemName}>{d.original_name}</div>
              <div style={styles.itemMeta}>
                <span style={{ color: statusColor(d.status) }}>● {STATUS_LABELS[d.status]}</span>
                {d.status === 'ready' && <span> · {d.chunks_count} фрагм.</span>}
                {d.status === 'error' && d.processing_error && <span style={{ color: theme.accent.red }}> · {d.processing_error}</span>}
              </div>
            </div>
            <button
              style={d.included ? styles.toggleOn : styles.toggleOff}
              onClick={() => toggleIncluded(d)}
              title={d.included ? 'В контексте — выключить' : 'Включить в контекст'}
            >
              {d.included ? 'в контексте' : 'выкл'}
            </button>
            <button style={styles.detachBtn} onClick={() => detach(d)}>✕</button>
          </div>
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
  uploadRow: { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' as const },
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
