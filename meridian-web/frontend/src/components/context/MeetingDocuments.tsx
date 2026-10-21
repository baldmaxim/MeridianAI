import { useState, useEffect, useRef, useCallback } from 'react';
import { listDocumentRecords, reprocessDocument } from '../../api/documents';
import { listMeetingDocuments, attachMeetingDocument, patchMeetingDocument, detachMeetingDocument } from '../../api/meetingDocuments';
import { apiErrorMessage } from '../../lib/apiError';
import type { MeetingDocument, DocumentRecord } from '../../types';
import { ContextSourceCard } from './ContextSourceCard';
import { documentToContextSourceViewModel, type ContextSourceSectionSummary } from './contextSourceModel';
import { useDocumentUploadQueue } from '../../hooks/useDocumentUploadQueue';
import { DocumentUploadQueue } from './DocumentUploadQueue';
import { Select } from '../common';
import styles from './MeetingDocuments.module.css';

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

  // eslint-disable-next-line react-hooks/set-state-in-effect -- setState внутри load только после await (асинхронно)
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
  useEffect(() => { onSummaryChangeRef.current = onSummaryChange; });
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
  useEffect(() => { onUploadActivityChangeRef.current = onUploadActivityChange; });
  useEffect(() => { onUploadActivityChangeRef.current?.(queue.activeCount); }, [queue.activeCount]);

  // поллинг, пока есть документы в обработке. Скан, ждущий агента распознавания, опрашиваем
  // редко: компьютер с LM Studio может быть выключен часами, но прогресс и «не на связи» видны.
  useEffect(() => {
    if (meetingId == null) return;
    const pendingExists = docs.some((d) => !['ready', 'error', 'awaiting_ocr'].includes(d.status));
    const awaitingOcr = docs.some((d) => d.status === 'awaiting_ocr' || !!d.ocr_note);
    if (!pendingExists && !awaitingOcr) return;
    const t = setInterval(load, pendingExists ? 3000 : 60000);
    return () => clearInterval(t);
  }, [docs, meetingId, load]);

  // существующие документы по объекту (для «выбрать существующий»)
  useEffect(() => {
    if (objectId == null) return;
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

  // Скан, упавший с «нужен OCR», сам не переобработается — перезапуск явный.
  // missingPages — готовый скан с пустыми страницами: агент досдаёт только их.
  async function reprocess(d: MeetingDocument, missingPages = false) {
    setError('');
    try {
      await reprocessDocument(d.document_id, { missingPages });
      await load();
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось запустить повторную обработку')); }
  }

  function primaryAction(d: MeetingDocument): { label: string; run: () => void } | undefined {
    if (d.status === 'error') return { label: 'Распознать заново', run: () => reprocess(d) };
    if (d.status === 'ready' && !d.ocr_note && (d.ocr_missing_pages?.length ?? 0) > 0) {
      return { label: 'Дораспознать', run: () => reprocess(d, true) };
    }
    return undefined;
  }

  const attachedIds = new Set(docs.map((d) => d.document_id));
  const available = (objectId == null ? [] : existing).filter((d) => !attachedIds.has(d.id) && d.status === 'ready');

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>Документы встречи</span>
        <span className={styles.spacer} />
        <button className={styles.refreshBtn} onClick={load} disabled={meetingId == null}>↻</button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {/* Загрузка: кнопка + drag-and-drop */}
      <div
        className={`${styles.dropZone} ${dragOver ? styles.dropZoneActive : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
          className={styles.hidden}
          onChange={(e) => {
            const f = e.target.files;
            if (f && f.length) { setError(''); queue.addFiles(Array.from(f)); }
            if (fileRef.current) fileRef.current.value = '';
          }}
        />
        <div className={styles.dropText}>
          {queue.hasActiveUploads
            ? 'Файлы загружаются — можно продолжать настройку встречи'
            : dragOver
              ? 'Отпустите файлы, чтобы добавить в контекст'
              : 'Перетащите файлы сюда или загрузите кнопкой'}
        </div>
        <div className={styles.uploadRow}>
          <button className={styles.uploadBtn} onClick={() => fileRef.current?.click()}>
            + Загрузить документ
          </button>
          <span className={styles.hint}>PDF, DOCX, XLSX, TXT, MD, CSV</span>
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
        <div className={styles.pickRow}>
          <Select
            className={styles.selectWrap}
            triggerClassName={styles.select}
            ariaLabel="Существующий документ"
            value={String(pickId)}
            onChange={(v) => setPickId(v === '' ? '' : Number(v))}
            options={[{ value: '', label: '— выбрать существующий —' },
              ...available.map((d) => ({ value: String(d.id), label: d.original_name }))]}
          />
          <button className={styles.attachBtn} onClick={attachExisting} disabled={pickId === ''}>Прикрепить</button>
        </div>
      )}

      {/* Список */}
      {docs.length === 0 && <div className={styles.empty}>Документы не прикреплены</div>}
      <div className={styles.list}>
        {docs.map((d) => (
          <ContextSourceCard
            key={d.id}
            source={documentToContextSourceViewModel(d)}
            onToggleIncluded={() => toggleIncluded(d)}
            onRemove={() => detach(d)}
            primaryActionLabel={primaryAction(d)?.label}
            onPrimaryAction={primaryAction(d)?.run}
          />
        ))}
      </div>
    </div>
  );
}
