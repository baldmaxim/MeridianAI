import { useState } from 'react';
import { CollapsibleSection } from '../common/CollapsibleSection';
import { MeetingDocuments } from './MeetingDocuments';
import { PreviousMeetingsContext } from './PreviousMeetingsContext';
import { ContextSourceCard } from './ContextSourceCard';
import { RagFolderPickerModal } from './RagFolderPickerModal';
import { ContextPreviewModal } from './ContextPreviewModal';
import {
  ragPlaceholderToContextSourceViewModel,
  ragAttachedFolderToContextSourceViewModel,
  attachedLetterToContextSourceViewModel,
  type ContextSourceSectionSummary,
} from './contextSourceModel';
import { useRagContextFolders } from '../../hooks/useRagContextFolders';
import { useMeetingLetters } from '../../hooks/useMeetingLetters';
import type { RagContextAdapter } from './ragContextTypes';
import styles from './ContextBasket.module.css';

interface Props {
  meetingId: number | null;
  customerId?: number | null;
  objectId?: number | null;
  ensureMeetingId?: () => Promise<number | null>;
  ragAdapter?: RagContextAdapter;
}

function chip(label: string, s: ContextSourceSectionSummary | null): string {
  if (!s || s.total === 0) return `${label}: 0`;
  return `${label}: ${s.included}/${s.total}`;
}

// Корзина контекста: единая визуальная зона «что попадёт в подсказки».
// Объединяет источники контекста встречи (документы, прошлые встречи, RAG).
export function ContextBasket({ meetingId, customerId, objectId, ensureMeetingId, ragAdapter }: Props) {
  const [docSummary, setDocSummary] = useState<ContextSourceSectionSummary | null>(null);
  const [prevSummary, setPrevSummary] = useState<ContextSourceSectionSummary | null>(null);
  const [uploadActive, setUploadActive] = useState(0);
  const [ragPickerOpen, setRagPickerOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  // TODO: connect real RAG adapter; source_type='rag_folder'
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

  const ragTotal = rag.attachedFolders.length;
  const ragIncluded = rag.attachedFolders.filter((x) => x.included).length;
  const ragChip = rag.enabled ? `RAG: ${ragIncluded}/${ragTotal}` : 'RAG: скоро';
  const letterTotal = letters.attached.length;
  const letterIncluded = letters.attached.filter((x) => x.included).length;

  return (
    <div className={styles.wrap}>
      <div className={styles.head}>
        <div className={styles.titleRow}>
          <span className={styles.dot} />
          <span className={styles.title}>Что попадёт в подсказки</span>
          <span className={styles.spacer} />
          <button type="button" className={styles.previewBtn} onClick={() => setPreviewOpen(true)}>
            Предпросмотр контекста
          </button>
        </div>
        <div className={styles.subtitle}>Добавьте документы, прошлые встречи или RAG-папки</div>
        <div className={styles.chips}>
          <span className={styles.chipItem}>{chip('Файлы', docSummary)}</span>
          {uploadActive > 0 && <span className={styles.chipActive}>Загрузка: {uploadActive}</span>}
          <span className={styles.chipItem}>{chip('Прошлые встречи', prevSummary)}</span>
          <span className={styles.chipItem}>{ragChip}</span>
          <span className={styles.chipItem}>{`Письма: ${letterIncluded}/${letterTotal}`}</span>
        </div>
      </div>

      <CollapsibleSection title="Файлы" defaultOpen>
        <MeetingDocuments
          meetingId={meetingId}
          customerId={customerId}
          objectId={objectId}
          ensureMeetingId={ensureMeetingId}
          onSummaryChange={setDocSummary}
          onUploadActivityChange={setUploadActive}
        />
      </CollapsibleSection>

      <CollapsibleSection title="Прошлые встречи">
        {meetingId != null ? (
          <PreviousMeetingsContext
            meetingId={meetingId}
            currentCustomerId={customerId}
            currentObjectId={objectId}
            onSummaryChange={setPrevSummary}
          />
        ) : (
          <div className={styles.hint}>
            Выберите заказчика или объект — встреча подготовится, и можно будет добавить прошлые встречи.
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="RAG-папки и письма">
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
            {letters.error && <span className={styles.ragNote}>{letters.error}</span>}
            {!rag.enabled && <span className={styles.ragNote}>Backend RAG ещё не подключён</span>}
          </div>
        </div>
      </CollapsibleSection>

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
    </div>
  );
}
