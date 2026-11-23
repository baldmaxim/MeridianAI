import { useCallback, useMemo, useRef, useState } from 'react';
import type { DragEvent, FC } from 'react';
import { SourceTreeFolder } from './SourceTreeFolder';
import { PreviousMeetingsContext } from './PreviousMeetingsContext';
import { ContextSourceCard } from './ContextSourceCard';
import { RagFolderPickerModal } from './RagFolderPickerModal';
import { ContextPreviewModal } from './ContextPreviewModal';
import { DocumentUploadQueue } from './DocumentUploadQueue';
import { OfferSubmissionSelect } from './OfferSubmissionSelect';
import { SourceFileRow } from './SourceFileRow';
import { getDocumentDisplayName } from '../../lib/documentName';
import {
  ragPlaceholderToContextSourceViewModel,
  ragAttachedFolderToContextSourceViewModel,
  attachedLetterToContextSourceViewModel,
} from './contextSourceModel';
import { buildDocGroups, countIncluded, isInherited } from './sourcesModel';
import { useRagContextFolders } from '../../hooks/useRagContextFolders';
import { useMeetingLetters } from '../../hooks/useMeetingLetters';
import { useDocumentUploadQueue } from '../../hooks/useDocumentUploadQueue';
import { useMeetingSources } from '../../hooks/useMeetingSources';
import { useOfferSubmissions } from '../../hooks/useOfferSubmissions';
import { useMeetingStore } from '../../store/meetingStore';
import { extractDroppedFiles } from '../../lib/documentFiles';
import type { MeetingDocument } from '../../types';
import type { RagContextAdapter } from './ragContextTypes';
import styles from './SourcesPanel.module.css';

interface ISourcesPanelProps {
  meetingId: number | null;
  customerId?: number | null;
  objectId?: number | null;
  ensureMeetingId?: () => Promise<number | null>;
  ragAdapter?: RagContextAdapter;
}

const FILE_ACCEPT = '.pdf,.docx,.xlsx,.txt,.md,.csv';

const hasFiles = (e: DragEvent): boolean => Array.from(e.dataTransfer.types).includes('Files');

/** Панель «Источники»: файлы встречи и унаследованные, прошлые встречи, RAG-папки и письма. Вся панель — зона drop. */
export const SourcesPanel: FC<ISourcesPanelProps> = ({
  meetingId, customerId, objectId, ensureMeetingId, ragAdapter,
}) => {
  const [ragPickerOpen, setRagPickerOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const dragDepth = useRef(0);
  const fileRef = useRef<HTMLInputElement>(null);

  const sources = useMeetingSources(meetingId);
  const offerSubmission = useMeetingStore((s) => s.selectedOfferSubmission);
  const submissions = useOfferSubmissions(objectId);
  const docGroups = useMemo(
    () => buildDocGroups(sources.filteredDocs, submissions, offerSubmission),
    [sources.filteredDocs, submissions, offerSubmission],
  );
  const { refresh } = sources;

  // Если ensureMeetingId не передан — fallback: вернуть текущий meetingId либо null.
  const ensureMeetingIdFn = useCallback(async (): Promise<number | null> => {
    if (ensureMeetingId) return ensureMeetingId();
    return meetingId;
  }, [ensureMeetingId, meetingId]);

  const queue = useDocumentUploadQueue({
    customerId,
    objectId,
    ensureMeetingId: ensureMeetingIdFn,
    onAttached: refresh,
    maxParallel: 1,
  });

  const ragPlaceholder = ragPlaceholderToContextSourceViewModel();
  const rag = useRagContextFolders({
    meetingId,
    customerId,
    objectId,
    adapter: ragAdapter,
    ensureMeetingId,
    open: ragPickerOpen,
  });
  const letters = useMeetingLetters({ meetingId, ensureMeetingId, open: ragPickerOpen });

  const addFiles = (files: File[]) => {
    if (!files.length) return;
    queue.addFiles(files);
  };

  const onDragEnter = (e: DragEvent) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth.current += 1;
    setDragOver(true);
  };
  const onDragOver = (e: DragEvent) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  };
  const onDragLeave = (e: DragEvent) => {
    if (!hasFiles(e)) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragOver(false);
  };
  const onDrop = (e: DragEvent) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth.current = 0;
    setDragOver(false);
    addFiles(extractDroppedFiles(e.dataTransfer));
  };

  const removeDoc = (doc: MeetingDocument) => {
    const question = isInherited(doc)
      ? `Скрыть «${getDocumentDisplayName(doc)}» из этой встречи?`
      : `Открепить «${getDocumentDisplayName(doc)}»?`;
    if (confirm(question)) void sources.remove(doc);
  };

  const hasDocs = sources.docs.length > 0;

  const groupState = (docs: MeetingDocument[]): 'all' | 'some' | 'none' => {
    const on = docs.filter((d) => d.included).length;
    return on === 0 ? 'none' : on === docs.length ? 'all' : 'some';
  };
  // Все включены → выключаем все; иначе включаем недостающие.
  const toggleGroup = (docs: MeetingDocument[]) => {
    const allOn = docs.every((d) => d.included);
    docs.filter((d) => d.included === allOn).forEach((d) => { void sources.toggleIncluded(d); });
  };

  const ragItems = [...rag.attachedFolders, ...letters.attached];
  const ragCounter = ragItems.length > 0
    ? `${ragItems.filter((i) => i.included).length} из ${ragItems.length}`
    : undefined;

  return (
    <section
      className={styles.panel}
      aria-label="Источники"
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <header className={styles.head}>
        <div className={styles.titleRow}>
          <h2 className={styles.title}>Источники</h2>
          <span className={styles.counter}>
            {sources.counter.included} из {sources.counter.total} в контексте
          </span>
          <button
            type="button"
            className={styles.previewBtn}
            onClick={() => setPreviewOpen(true)}
            aria-label="Предпросмотр контекста"
            title="Предпросмотр контекста"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept={FILE_ACCEPT}
            className={styles.hidden}
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []));
              if (fileRef.current) fileRef.current.value = '';
            }}
          />
          <button
            type="button"
            className={styles.addBtn}
            onClick={() => fileRef.current?.click()}
            aria-label="Добавить файлы"
            title="PDF, DOCX, XLSX, TXT, MD, CSV — можно перетащить в список"
          >
            + Файлы
          </button>
        </div>

        {sources.error && <div className={styles.error} role="alert">{sources.error}</div>}

        <DocumentUploadQueue
          items={queue.items}
          onRetry={queue.retryItem}
          onCancel={queue.cancelItem}
          onClearItem={queue.clearItem}
          onClearFinished={queue.clearFinished}
        />

        {meetingId != null && objectId != null && (
          <OfferSubmissionSelect
            submissions={submissions}
            value={offerSubmission}
            onChange={(v) => { void sources.changeOfferSubmission(v); }}
          />
        )}

        {sources.typeChips.length >= 2 && (
          <div className={styles.filters} role="group" aria-label="Фильтр по типу документа">
            <button
              type="button"
              className={`${styles.filterChip} ${sources.activeType == null ? styles.filterChipOn : ''}`}
              aria-pressed={sources.activeType == null}
              onClick={() => sources.setTypeFilter(null)}
            >
              Все
            </button>
            {sources.typeChips.map((c) => (
              <button
                key={c.key}
                type="button"
                className={`${styles.filterChip} ${sources.activeType === c.key ? styles.filterChipOn : ''}`}
                aria-pressed={sources.activeType === c.key}
                onClick={() => sources.setTypeFilter(c.key)}
              >
                {c.label} · {c.count}
              </button>
            ))}
          </div>
        )}
      </header>

      {/* Дерево источников: папки без карточек, файлы с отступом. Весь список — зона drop. */}
      <div className={`${styles.tree} ${dragOver ? styles.treeDrag : ''}`}>
        {!hasDocs && (
          <div className={styles.emptyHint}>
            {dragOver ? 'Отпустите — тип определится автоматически' : 'Перетащите файлы в список или нажмите «+ Файлы»'}
          </div>
        )}

        {docGroups.map((g) => {
          const { included, total } = countIncluded(g.docs);
          return (
            <SourceTreeFolder
              key={g.id}
              title={g.title}
              defaultOpen={g.defaultOpen}
              counter={`${included} из ${total}`}
              checked={groupState(g.docs)}
              onToggleAll={() => toggleGroup(g.docs)}
            >
              <ul className={styles.list}>
                {g.docs.map((d) => (
                  <SourceFileRow
                    key={d.document_id}
                    doc={d}
                    onToggleIncluded={sources.toggleIncluded}
                    onRemove={removeDoc}
                    onReprocess={sources.reprocess}
                  />
                ))}
              </ul>
            </SourceTreeFolder>
          );
        })}

        <SourceTreeFolder title="Прошлые встречи">
          {meetingId != null ? (
            <PreviousMeetingsContext
              variant="flat"
              meetingId={meetingId}
              currentCustomerId={customerId}
              currentObjectId={objectId}
            />
          ) : (
            <div className={styles.note}>
              Выберите заказчика или объект — встреча подготовится, и можно будет добавить прошлые встречи.
            </div>
          )}
        </SourceTreeFolder>

        <SourceTreeFolder title="Папки и письма" counter={ragCounter}>
          <div className={styles.ragSection}>
            {ragItems.length === 0 ? (
              <ContextSourceCard source={ragPlaceholder} flat />
            ) : (
              <>
                {rag.attachedFolders.map((s) => (
                  <ContextSourceCard
                    key={s.sourceId}
                    flat
                    source={ragAttachedFolderToContextSourceViewModel(s)}
                    onToggleIncluded={() => rag.toggleIncluded(s.sourceId, !s.included)}
                    onPriorityChange={(p) => rag.updatePriority(s.sourceId, p)}
                    onRemove={() => rag.detachFolder(s.sourceId)}
                  />
                ))}
                {letters.attached.map((m) => (
                  <ContextSourceCard
                    key={`letter-${m.sourceId}`}
                    flat
                    source={attachedLetterToContextSourceViewModel(m)}
                    onToggleIncluded={() => letters.toggleIncluded(m.sourceId, !m.included)}
                    onPriorityChange={(p) => letters.updatePriority(m.sourceId, p)}
                    onRemove={() => letters.detach(m.sourceId)}
                  />
                ))}
              </>
            )}
            <div className={styles.ragActions}>
              <button type="button" className={styles.ragPickBtn} onClick={() => setRagPickerOpen(true)}>
                Выбрать папку или письмо
              </button>
              {letters.error && <span className={styles.note}>{letters.error}</span>}
              {!rag.enabled && <span className={styles.note}>Backend RAG ещё не подключён</span>}
            </div>
          </div>
        </SourceTreeFolder>
      </div>

      <ContextPreviewModal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        meetingId={meetingId}
      />

      <RagFolderPickerModal
        open={ragPickerOpen}
        onClose={() => setRagPickerOpen(false)}
        enabled={rag.enabled}
        disabledReason={rag.disabledReason}
        folders={rag.folders}
        attachedFolders={rag.attachedFolders}
        loading={rag.loading}
        refreshing={rag.refreshing}
        error={rag.error}
        query={rag.query}
        onQueryChange={rag.setQuery}
        onRefresh={rag.refresh}
        onAttachFolder={rag.attachFolder}
        onDetachFolder={rag.detachFolder}
        onToggleIncluded={rag.toggleIncluded}
        onPriorityChange={rag.updatePriority}
        letters={letters}
      />
    </section>
  );
};
