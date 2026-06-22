import { useCallback, useEffect, useRef, useState } from 'react';
import { apiErrorMessage } from '../lib/apiError';
import {
  searchLetters,
  listMeetingLetters,
  attachMeetingLetter,
  updateMeetingLetter,
  detachMeetingLetter,
  type LetterHit,
  type MeetingLetter,
} from '../api/letters';

interface UseMeetingLettersOptions {
  meetingId: number | null;
  projectId?: number | null; // фильтр по проекту PayHub (опц.)
  ensureMeetingId?: () => Promise<number | null>;
  open?: boolean; // модалка открыта — грузить прикреплённые
}

// Управляет ручным выбором писем PayHub для контекста встречи: поиск (api/letters) +
// прикреплённые к встрече письма (/meetings/{id}/letters).
export function useMeetingLetters(options: UseMeetingLettersOptions) {
  const { meetingId, projectId, ensureMeetingId, open } = options;

  const [results, setResults] = useState<LetterHit[]>([]);
  const [attached, setAttached] = useState<MeetingLetter[]>([]);
  const [loading, setLoading] = useState(false); // загрузка прикреплённых
  const [searching, setSearching] = useState(false); // поиск
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const meetingRef = useRef(meetingId); meetingRef.current = meetingId;
  const ensureRef = useRef(ensureMeetingId); ensureRef.current = ensureMeetingId;
  const projectRef = useRef(projectId); projectRef.current = projectId;
  const queryRef = useRef(query); queryRef.current = query;

  const loadAttached = useCallback(async () => {
    const mid = meetingRef.current;
    if (mid == null) { setAttached([]); return; }
    setLoading(true); setError(null);
    try {
      setAttached(await listMeetingLetters(mid));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось загрузить письма встречи'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void loadAttached();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, meetingId]);

  const search = useCallback(async () => {
    const q = queryRef.current.trim();
    if (!q) { setResults([]); return; }
    setSearching(true); setError(null);
    try {
      setResults(await searchLetters({ query: q, k: 12, projectId: projectRef.current ?? null }));
    } catch (e) {
      setResults([]);
      setError(apiErrorMessage(e, 'Не удалось выполнить поиск по письмам'));
    } finally {
      setSearching(false);
    }
  }, []);

  const attach = useCallback(async (hit: LetterHit) => {
    setError(null);
    try {
      let mid = meetingRef.current;
      if (mid == null && ensureRef.current) mid = await ensureRef.current();
      if (mid == null) { setError('Не удалось создать встречу для добавления письма'); return; }
      const item = await attachMeetingLetter(mid, hit);
      setAttached((prev) => [
        ...prev.filter((x) => x.sourceId !== item.sourceId && x.chunkId !== item.chunkId),
        item,
      ]);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось добавить письмо'));
    }
  }, []);

  const detach = useCallback(async (sourceId: number) => {
    const mid = meetingRef.current;
    if (mid == null) return;
    setError(null);
    try {
      await detachMeetingLetter(mid, sourceId);
      setAttached((prev) => prev.filter((x) => x.sourceId !== sourceId));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось убрать письмо'));
    }
  }, []);

  const toggleIncluded = useCallback(async (sourceId: number, included: boolean) => {
    const mid = meetingRef.current;
    if (mid == null) return;
    setError(null);
    try {
      const upd = await updateMeetingLetter(mid, sourceId, { included });
      setAttached((prev) => prev.map((x) => (x.sourceId === sourceId ? upd : x)));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось обновить письмо'));
    }
  }, []);

  const updatePriority = useCallback(async (sourceId: number, priority: number) => {
    const mid = meetingRef.current;
    if (mid == null) return;
    setError(null);
    try {
      const upd = await updateMeetingLetter(mid, sourceId, { priority });
      setAttached((prev) => prev.map((x) => (x.sourceId === sourceId ? upd : x)));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось обновить приоритет'));
    }
  }, []);

  return {
    results, attached, loading, searching, error,
    query, setQuery, search,
    attach, detach, toggleIncluded, updatePriority, reload: loadAttached,
  };
}
