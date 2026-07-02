import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createDocumentUploadSession, putFileToPresignedUrl, confirmDocumentUpload, uploadDocument,
} from '../api/documents';
import { attachMeetingDocument } from '../api/meetingDocuments';
import { apiErrorMessage } from '../lib/apiError';
import {
  isSupportedDocumentFile, getFileExtension, makeUploadClientId,
} from '../lib/documentFiles';

export type DocumentUploadQueueStatus =
  | 'queued'
  | 'creating_session'
  | 'uploading'
  | 'confirming'
  | 'attaching'
  | 'processing'
  | 'done'
  | 'error'
  | 'cancelled';

export interface DocumentUploadQueueItem {
  clientId: string;
  file: File;
  fileName: string;
  fileSize: number;
  status: DocumentUploadQueueStatus;
  progress: number;
  error?: string;
  documentId?: number;
  startedAt?: number;
  finishedAt?: number;
}

interface UseDocumentUploadQueueOptions {
  customerId?: number | null;
  objectId?: number | null;
  ensureMeetingId: () => Promise<number | null>;
  onAttached?: () => Promise<void> | void;
  maxParallel?: number;
}

const ACTIVE_STATUSES: ReadonlySet<DocumentUploadQueueStatus> = new Set([
  'creating_session', 'uploading', 'confirming', 'attaching', 'processing',
]);
const TERMINAL_STATUSES: ReadonlySet<DocumentUploadQueueStatus> = new Set([
  'done', 'error', 'cancelled',
]);

const UNSUPPORTED_MSG = 'Допустимые: PDF, DOCX, XLSX, TXT, MD, CSV';
const DONE_AUTO_CLEAR_MS = 3000;

// Сигнал отмены: отличаем «пользователь отменил» от настоящей ошибки сети/бэка.
class CancelledError extends Error {}

function dupKey(file: File): string {
  return `${file.name}:${file.size}`;
}

export function useDocumentUploadQueue(options: UseDocumentUploadQueueOptions) {
  const [items, setItemsState] = useState<DocumentUploadQueueItem[]>([]);

  // Источник истины для асинхронного «насоса»: синхронно доступен, без stale-closure.
  const itemsRef = useRef<DocumentUploadQueueItem[]>([]);
  const optsRef = useRef(options);
  optsRef.current = options;

  const startedRef = useRef<Set<string>>(new Set());
  const abortRef = useRef<Map<string, AbortController>>(new Map());
  const doneTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const processItemRef = useRef<(clientId: string) => Promise<void>>(() => Promise.resolve());
  const pumpRef = useRef<() => void>(() => {});

  const commit = useCallback((next: DocumentUploadQueueItem[]) => {
    itemsRef.current = next;
    setItemsState(next);
  }, []);

  const patch = useCallback((clientId: string, partial: Partial<DocumentUploadQueueItem>) => {
    commit(itemsRef.current.map((it) => (it.clientId === clientId ? { ...it, ...partial } : it)));
  }, [commit]);

  // Запустить столько queued-элементов, сколько позволяет maxParallel.
  const pump = useCallback(() => {
    const max = optsRef.current.maxParallel ?? 1;
    const active = itemsRef.current.filter((i) => ACTIVE_STATUSES.has(i.status)).length;
    let slots = max - active;
    if (slots <= 0) return;
    for (const it of itemsRef.current) {
      if (slots <= 0) break;
      if (it.status === 'queued' && !startedRef.current.has(it.clientId)) {
        slots -= 1;
        void processItemRef.current(it.clientId);
      }
    }
  }, []);
  pumpRef.current = pump;

  const processItem = useCallback(async (clientId: string) => {
    if (startedRef.current.has(clientId)) return;
    const start = itemsRef.current.find((i) => i.clientId === clientId);
    if (!start || start.status === 'cancelled') return;
    startedRef.current.add(clientId);

    const ac = new AbortController();
    abortRef.current.set(clientId, ac);
    const cancelled = () => ac.signal.aborted
      || itemsRef.current.find((i) => i.clientId === clientId)?.status === 'cancelled';
    const guard = () => { if (cancelled()) throw new CancelledError(); };

    try {
      let documentId = start.documentId;

      // Если файл уже загружен (retry после ошибки attach) — пропускаем upload.
      if (documentId == null) {
        patch(clientId, { status: 'creating_session', progress: 0, error: undefined, startedAt: Date.now() });
        const meetingId = await optsRef.current.ensureMeetingId();
        guard();
        if (meetingId == null) {
          patch(clientId, { status: 'error', error: 'Не удалось создать встречу для загрузки документа', finishedAt: Date.now() });
          return;
        }
        const session = await createDocumentUploadSession(
          start.file,
          { customer_id: optsRef.current.customerId ?? null, object_id: optsRef.current.objectId ?? null },
          ac.signal,
        );
        guard();

        // Этап 22: S3 выключен/kill-switch → legacy multipart (in-memory session). Без S3-PUT,
        // confirm/attach через documentId неприменимы: legacy сам привязывает к активной встрече.
        if (session.upload_mode === 'legacy_multipart' || !session.upload_url || session.document_id == null) {
          patch(clientId, { status: 'uploading', progress: 0 });
          await uploadDocument(start.file, 'other');
          guard();
          await optsRef.current.onAttached?.();
          patch(clientId, { status: 'done', progress: 1, finishedAt: Date.now() });
          return;
        }

        // documentId фиксируем в состоянии очереди ТОЛЬКО после успешного confirm — иначе retry
        // после сбоя PUT увидел бы documentId и перескочил бы на attach неотправленного файла.
        const newDocId = session.document_id;
        patch(clientId, { status: 'uploading', progress: 0 });

        await putFileToPresignedUrl(
          session.upload_url, start.file, session.headers,
          (frac) => patch(clientId, { progress: frac }), ac.signal,
        );
        guard();

        patch(clientId, { status: 'confirming', progress: 1 });
        await confirmDocumentUpload(newDocId, ac.signal);
        guard();

        documentId = newDocId;
        patch(clientId, { documentId });  // теперь retry-after-attach начнётся с attach
      }

      // attach — точка входа для retry, если ошибка была именно здесь.
      patch(clientId, { status: 'attaching', progress: 1 });
      const meetingId = await optsRef.current.ensureMeetingId();
      guard();
      if (meetingId == null) {
        patch(clientId, { status: 'error', error: 'Не удалось создать встречу для загрузки документа', finishedAt: Date.now() });
        return;
      }
      try {
        await attachMeetingDocument(meetingId, documentId);
      } catch {
        if (cancelled()) throw new CancelledError();
        patch(clientId, { status: 'error', error: 'Файл загружен, но не добавлен в контекст', finishedAt: Date.now() });
        return;
      }
      guard();

      await optsRef.current.onAttached?.();
      patch(clientId, { status: 'done', progress: 1, finishedAt: Date.now() });
    } catch (e) {
      if (e instanceof CancelledError || ac.signal.aborted) {
        patch(clientId, { status: 'cancelled', finishedAt: Date.now() });
      } else {
        patch(clientId, { status: 'error', error: apiErrorMessage(e, 'Ошибка загрузки документа'), finishedAt: Date.now() });
      }
    } finally {
      abortRef.current.delete(clientId);
      startedRef.current.delete(clientId);
      pumpRef.current();
    }
  }, [patch]);
  processItemRef.current = processItem;

  const addFiles = useCallback((files: File[]) => {
    if (!files.length) return;
    const additions: DocumentUploadQueueItem[] = [];
    // Дедуп: внутри пачки + против ещё не завершённых ошибкой/отменой элементов очереди.
    const seen = new Set(
      itemsRef.current
        .filter((i) => !TERMINAL_STATUSES.has(i.status) || i.status === 'done')
        .map((i) => dupKey(i.file)),
    );
    for (const file of files) {
      const base = {
        clientId: makeUploadClientId(file),
        file,
        fileName: file.name,
        fileSize: file.size,
        progress: 0,
      };
      if (!isSupportedDocumentFile(file)) {
        const ext = getFileExtension(file.name) || '—';
        additions.push({ ...base, status: 'error', error: `Формат ${ext} не поддерживается. ${UNSUPPORTED_MSG}` });
        continue;
      }
      const key = dupKey(file);
      if (seen.has(key)) {
        additions.push({ ...base, status: 'error', error: 'Файл уже добавлен в очередь' });
        continue;
      }
      seen.add(key);
      additions.push({ ...base, status: 'queued' });
    }
    commit([...itemsRef.current, ...additions]);
    pumpRef.current();
  }, [commit]);

  const retryItem = useCallback((clientId: string) => {
    const it = itemsRef.current.find((i) => i.clientId === clientId);
    if (!it || (it.status !== 'error' && it.status !== 'cancelled')) return;
    // documentId сохраняем: retry-after-attach начнёт сразу с attach.
    patch(clientId, { status: 'queued', progress: 0, error: undefined, finishedAt: undefined });
    pumpRef.current();
  }, [patch]);

  const cancelItem = useCallback((clientId: string) => {
    const it = itemsRef.current.find((i) => i.clientId === clientId);
    if (!it) return;
    const ac = abortRef.current.get(clientId);
    if (ac) ac.abort();
    if (it.status === 'queued' || ACTIVE_STATUSES.has(it.status)) {
      patch(clientId, { status: 'cancelled', finishedAt: Date.now() });
    }
  }, [patch]);

  const clearFinished = useCallback(() => {
    commit(itemsRef.current.filter((i) => !TERMINAL_STATUSES.has(i.status)));
  }, [commit]);

  const clearItem = useCallback((clientId: string) => {
    const it = itemsRef.current.find((i) => i.clientId === clientId);
    if (!it || ACTIVE_STATUSES.has(it.status)) return;
    commit(itemsRef.current.filter((i) => i.clientId !== clientId));
  }, [commit]);

  // Авто-уборка успешных (done) элементов через 3с. error/cancelled остаются.
  useEffect(() => {
    for (const it of items) {
      if (it.status === 'done' && !doneTimersRef.current.has(it.clientId)) {
        const t = setTimeout(() => {
          doneTimersRef.current.delete(it.clientId);
          commit(itemsRef.current.filter((x) => !(x.clientId === it.clientId && x.status === 'done')));
        }, DONE_AUTO_CLEAR_MS);
        doneTimersRef.current.set(it.clientId, t);
      }
    }
  }, [items, commit]);

  // Размонтирование: гасим таймеры и прерываем активные загрузки.
  useEffect(() => {
    const timers = doneTimersRef.current;
    const aborts = abortRef.current;
    return () => {
      timers.forEach(clearTimeout);
      aborts.forEach((ac) => ac.abort());
    };
  }, []);

  const activeCount = useMemo(
    () => items.filter((i) => ACTIVE_STATUSES.has(i.status)).length,
    [items],
  );

  return {
    items,
    activeCount,
    hasActiveUploads: activeCount > 0,
    addFiles,
    retryItem,
    cancelItem,
    clearFinished,
    clearItem,
  };
}
