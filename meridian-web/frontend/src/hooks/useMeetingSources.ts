import { useCallback, useEffect, useMemo, useState } from 'react';
import { getClassificationVocab, reprocessDocument } from '../api/documents';
import { detachMeetingDocument, listMeetingDocuments, patchMeetingDocument } from '../api/meetingDocuments';
import { apiErrorMessage } from '../lib/apiError';
import type { DocClassificationVocab, MeetingDocument } from '../types';
import {
  buildTypeChips, countIncluded, filterByType, getPollInterval, groupBySource,
} from '../components/context/sourcesModel';

const EMPTY_VOCAB: DocClassificationVocab = { doc_types: [], doc_tags: [] };

// Словарь типов/тегов почти не меняется — грузим один раз на сессию страницы.
let vocabPromise: Promise<DocClassificationVocab> | null = null;

const loadVocabOnce = (): Promise<DocClassificationVocab> => {
  if (!vocabPromise) {
    vocabPromise = getClassificationVocab().catch((e: unknown) => {
      vocabPromise = null; // при сбое попробуем снова при следующем монтировании
      throw e;
    });
  }
  return vocabPromise;
};

/** Источники контекста встречи (документы): список, опрос, включение/удаление, фильтр по типу. */
export const useMeetingSources = (meetingId: number | null) => {
  const [rawDocs, setRawDocs] = useState<MeetingDocument[]>([]);
  const [vocab, setVocab] = useState<DocClassificationVocab>(EMPTY_VOCAB);
  const [error, setError] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | null>(null);

  const docs = useMemo(() => (meetingId == null ? [] : rawDocs), [meetingId, rawDocs]);

  const refresh = useCallback(async () => {
    if (meetingId == null) return;
    try {
      setRawDocs(await listMeetingDocuments(meetingId));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось загрузить документы'));
    }
  }, [meetingId]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- setState внутри refresh только после await (асинхронно)
  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    loadVocabOnce().then((v) => { if (!cancelled) setVocab(v); }).catch(() => { /* фолбэк на подписи из документов */ });
    return () => { cancelled = true; };
  }, []);

  // Опрос, пока есть документы в обработке (и редкий — пока скан ждёт OCR).
  const pollMs = meetingId == null ? null : getPollInterval(docs);
  useEffect(() => {
    if (pollMs == null) return;
    const t = setInterval(() => { void refresh(); }, pollMs);
    return () => clearInterval(t);
  }, [pollMs, refresh]);

  // Оптимистичное переключение «в контексте» с откатом при ошибке.
  const toggleIncluded = useCallback(async (doc: MeetingDocument) => {
    if (meetingId == null) return;
    const next = !doc.included;
    const setIncluded = (value: boolean) =>
      setRawDocs((prev) => prev.map((d) => (d.document_id === doc.document_id ? { ...d, included: value } : d)));
    setError('');
    setIncluded(next);
    try {
      await patchMeetingDocument(meetingId, doc.document_id, { included: next });
    } catch (e) {
      setIncluded(doc.included);
      setError(apiErrorMessage(e, 'Не удалось изменить участие в контексте'));
    }
  }, [meetingId]);

  /** Открепить (файл встречи) или скрыть из встречи (унаследованный) — на бэкенде это DELETE. */
  const remove = useCallback(async (doc: MeetingDocument) => {
    if (meetingId == null) return;
    setError('');
    try {
      await detachMeetingDocument(meetingId, doc.document_id);
      await refresh();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось убрать документ'));
    }
  }, [meetingId, refresh]);

  // Скан, упавший с «нужен OCR», сам не переобработается — перезапуск явный.
  const reprocess = useCallback(async (doc: MeetingDocument, missingPages = false) => {
    setError('');
    try {
      await reprocessDocument(doc.document_id, { missingPages });
      await refresh();
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось запустить повторную обработку'));
    }
  }, [refresh]);

  const typeChips = useMemo(() => buildTypeChips(docs, vocab.doc_types), [docs, vocab.doc_types]);
  // Выбранный тип мог исчезнуть из списка (документ удалён) — тогда фильтр сбрасывается.
  const activeType = typeChips.some((c) => c.key === typeFilter) ? typeFilter : null;
  const groups = useMemo(() => groupBySource(filterByType(docs, activeType)), [docs, activeType]);
  const counter = useMemo(() => countIncluded(docs), [docs]);

  return {
    docs, groups, typeChips, activeType, setTypeFilter, counter, error,
    refresh, toggleIncluded, remove, reprocess,
  };
};
