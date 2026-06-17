import { useCallback, useEffect, useRef, useState } from 'react';
import { apiErrorMessage } from '../lib/apiError';
import {
  disabledRagContextAdapter,
  type RagContextAdapter,
  type RagFolderViewModel,
  type RagAttachedFolderViewModel,
} from '../components/context/ragContextTypes';

interface UseRagContextFoldersOptions {
  meetingId: number | null;
  customerId?: number | null;
  objectId?: number | null;
  adapter?: RagContextAdapter;
  ensureMeetingId?: () => Promise<number | null>;
  open?: boolean;
}

// Управляет RAG-папками через адаптер. По умолчанию adapter отключён
// (disabledRagContextAdapter) — никаких сетевых запросов.
export function useRagContextFolders(options: UseRagContextFoldersOptions) {
  const adapter = options.adapter ?? disabledRagContextAdapter;
  const { meetingId, customerId, objectId, ensureMeetingId, open } = options;

  const [folders, setFolders] = useState<RagFolderViewModel[]>([]);
  const [attachedFolders, setAttachedFolders] = useState<RagAttachedFolderViewModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  // Refs, чтобы load/мутации были стабильны и читали свежие значения.
  const adapterRef = useRef(adapter); adapterRef.current = adapter;
  const queryRef = useRef(query); queryRef.current = query;
  const custRef = useRef(customerId); custRef.current = customerId;
  const objRef = useRef(objectId); objRef.current = objectId;
  const meetingRef = useRef(meetingId); meetingRef.current = meetingId;
  const ensureRef = useRef(ensureMeetingId); ensureRef.current = ensureMeetingId;

  const load = useCallback(async (mode: 'initial' | 'refresh') => {
    const a = adapterRef.current;
    if (!a.enabled) { setFolders([]); setAttachedFolders([]); return; }
    if (mode === 'refresh') setRefreshing(true); else setLoading(true);
    setError(null);
    try {
      const res = await a.listFolders({
        query: queryRef.current || undefined,
        customerId: custRef.current ?? null,
        objectId: objRef.current ?? null,
      });
      setFolders(res.folders);
      setAttachedFolders(meetingRef.current != null ? await a.listAttachedFolders(meetingRef.current) : []);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось загрузить RAG-папки'));
    } finally {
      setRefreshing(false); setLoading(false);
    }
  }, []);

  const refresh = useCallback(() => { void load('refresh'); }, [load]);

  // Автозагрузка при открытии — только если adapter включён.
  useEffect(() => {
    if (open && adapter.enabled) void load('initial');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, adapter.enabled, meetingId]);

  const attachFolder = useCallback(async (folderId: string) => {
    const a = adapterRef.current;
    if (!a.enabled) { setError(a.disabledReason ?? 'RAG ещё не подключён'); return; }
    setError(null);
    try {
      let mid = meetingRef.current;
      if (mid == null && ensureRef.current) mid = await ensureRef.current();
      if (mid == null) { setError('Не удалось создать встречу для добавления RAG-папки'); return; }
      const src = await a.attachFolder(mid, folderId);
      setAttachedFolders((prev) => [...prev.filter((x) => x.sourceId !== src.sourceId), src]);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось добавить RAG-папку'));
    }
  }, []);

  const detachFolder = useCallback(async (sourceId: string) => {
    const a = adapterRef.current;
    if (!a.enabled) { setError(a.disabledReason ?? 'RAG ещё не подключён'); return; }
    const mid = meetingRef.current;
    if (mid == null) return;
    setError(null);
    try {
      await a.detachFolder(mid, sourceId);
      setAttachedFolders((prev) => prev.filter((x) => x.sourceId !== sourceId));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось убрать RAG-папку'));
    }
  }, []);

  const toggleIncluded = useCallback(async (sourceId: string, included: boolean) => {
    const a = adapterRef.current;
    if (!a.enabled) { setError(a.disabledReason ?? 'RAG ещё не подключён'); return; }
    const mid = meetingRef.current;
    if (mid == null) return;
    setError(null);
    try {
      const upd = await a.updateAttachedFolder(mid, sourceId, { included });
      setAttachedFolders((prev) => prev.map((x) => (x.sourceId === sourceId ? upd : x)));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось обновить RAG-папку'));
    }
  }, []);

  const updatePriority = useCallback(async (sourceId: string, priority: number) => {
    const a = adapterRef.current;
    if (!a.enabled) { setError(a.disabledReason ?? 'RAG ещё не подключён'); return; }
    const mid = meetingRef.current;
    if (mid == null) return;
    setError(null);
    try {
      const upd = await a.updateAttachedFolder(mid, sourceId, { priority });
      setAttachedFolders((prev) => prev.map((x) => (x.sourceId === sourceId ? upd : x)));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось обновить приоритет'));
    }
  }, []);

  return {
    enabled: adapter.enabled,
    disabledReason: adapter.disabledReason,
    folders,
    attachedFolders,
    loading,
    refreshing,
    error,
    query,
    setQuery,
    refresh,
    attachFolder,
    detachFolder,
    toggleIncluded,
    updatePriority,
  };
}
