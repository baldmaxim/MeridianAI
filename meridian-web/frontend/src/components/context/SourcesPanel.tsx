import { useCallback, useRef, useState } from 'react';
import type { DragEvent, FC } from 'react';
import { CollapsibleSection } from '../common/CollapsibleSection';
import { PreviousMeetingsContext } from './PreviousMeetingsContext';
import { ContextSourceCard } from './ContextSourceCard';
import { RagFolderPickerModal } from './RagFolderPickerModal';
import { ContextPreviewModal } from './ContextPreviewModal';
import { DocumentUploadQueue } from './DocumentUploadQueue';
import { SourceFileRow } from './SourceFileRow';
import {
  ragPlaceholderToContextSourceViewModel,
  ragAttachedFolderToContextSourceViewModel,
  attachedLetterToContextSourceViewModel,
} from './contextSourceModel';
import { isInherited } from './sourcesModel';
import { useRagContextFolders } from '../../hooks/useRagContextFolders';
import { useMeetingLetters } from '../../hooks/useMeetingLetters';
import { useDocumentUploadQueue } from '../../hooks/useDocumentUploadQueue';
import { useMeetingSources } from '../../hooks/useMeetingSources';
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
      ? `Скрыть «${doc.original_name}» из этой встречи?`
      : `Открепить «${doc.original_name}»?`;
    if (confirm(question)) void sources.remove(doc);
  };

  const hasDocs = sources.docs.length > 0;

  return (
    <section
      className={styles.panel}
      aria-label="Источники"
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className={`${styles.overlay} ${dragOver ? styles.overlayActive : ''}`} aria-hidden>
        <span className={styles.overlayText}>Отпустите файлы — тип определится автоматически</span>
      </div>

      <div className={styles.scroll}>
        <header className={styles.head}>
          <div className={styles.titleRow}>
            <span className={styles.dot} />
            <h2 className={styles.title}>Источники</h2>
            <button type="button" className={styles.previewBtn} onClick={() => setPreviewOpen(true)}>
              Предпросмотр контекста
            </button>
          </div>
          <div className={styles.counter}>
            в контексте {sources.counter.included} из {sources.counter.total}
          </div>
          <div className={styles.addRow}>
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
            <button type="button" className={styles.addBtn} onClick={() => fileRef.current?.click()}>
              + Добавить файлы
            </button>
            <span className={styles.hint}>PDF, DOCX, XLSX, TXT, MD, CSV — можно перетащить в панель</span>
          </div>
        </header>

        {sources.error && <div className={styles.error} role="alert">{sources.error}</div>}

        <DocumentUploadQueue
          items={queue.items}
          onRetry={queue.retryItem}
          onCancel={queue.cancelItem}
          onClearItem={queue.clearItem}
          onClearFinished={queue.clearFinished}
        />

        {sources.typeChips.length > 0 && (
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

        {!hasDocs && (
          <div className={styles.empty}>
            Файлов пока нет — перетащите их в панель или нажмите «+ Добавить файлы»
          </div>
        )}
        {sources.groups.map((g) => (
          <div key={g.source} className={styles.group}>
            <h3 className={styles.groupTitle}>{g.title} · {g.docs.length}</h3>
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
          </div>
        ))}

        <CollapsibleSection title="Прошлые встречи">
          {meetingId != null ? (
            <PreviousMeetingsContext
              meetingId={meetingId}
              currentCustomerId={customerId}
              currentObjectId={objectId}
            />
          ) : (
            <div className={styles.note}>
              Выберите заказчика или объект — встреча подготовится, и можно будет добавить прошлые встречи.
            </div>
          )}
        </CollapsibleSection>

        <CollapsibleSection title="Папки и письма">
          <div className={styles.ragSection}>
            {rag.attachedFolders.length === 0 && letters.attached.length === 0 ? (
              <ContextSourceCard source={ragPlaceholder} />
            ) : (
              <>
                {rag.attachedFolders.map((s) => (
                  <ContextSourceCard
                    key={s.sourceId}
                    source={ragAttachedFolderToContextSourceViewModel(s)}
                    onToggleIncluded={() => rag.toggleIncluded(s.sourceId, !s.included)}
                    onPriorityChange={(p) => rag.updatePriority(s.sourceId, p)}
                    onRemove={() => rag.detachFolder(s.sourceId)}
                  />
                ))}
                {letters.attached.map((m) => (
                  <ContextSourceCard
                    key={`letter-${m.sourceId}`}
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
        </CollapsibleSection>
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
