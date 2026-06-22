import { useState } from 'react';
import { theme } from '../../styles/theme';
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
    <div style={styles.wrap}>
      <div style={styles.head}>
        <div style={styles.titleRow}>
          <span style={styles.dot} />
          <span style={styles.title}>Что попадёт в подсказки</span>
          <span style={{ flex: 1 }} />
          <button type="button" style={styles.previewBtn} onClick={() => setPreviewOpen(true)}>
            Предпросмотр контекста
          </button>
        </div>
        <div style={styles.subtitle}>Добавьте документы, прошлые встречи или RAG-папки</div>
        <div style={styles.chips}>
          <span style={styles.chipItem}>{chip('Файлы', docSummary)}</span>
          {uploadActive > 0 && <span style={styles.chipActive}>Загрузка: {uploadActive}</span>}
          <span style={styles.chipItem}>{chip('Прошлые встречи', prevSummary)}</span>
          <span style={styles.chipItem}>{ragChip}</span>
          <span style={styles.chipItem}>{`Письма: ${letterIncluded}/${letterTotal}`}</span>
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
          <div style={styles.hint}>
            Выберите заказчика или объект — встреча подготовится, и можно будет добавить прошлые встречи.
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="RAG-папки и письма">
        <div style={styles.ragSection}>
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
          <div style={styles.ragActions}>
            <button type="button" style={styles.ragPickBtn} onClick={() => setRagPickerOpen(true)}>
              Выбрать папку или письмо
            </button>
            {letters.error && <span style={styles.ragNote}>{letters.error}</span>}
            {!rag.enabled && <span style={styles.ragNote}>Backend RAG ещё не подключён</span>}
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

const styles: Record<string, React.CSSProperties> = {
  wrap: { display: 'flex', flexDirection: 'column', gap: 14 },
  head: { display: 'flex', flexDirection: 'column', gap: 6 },
  titleRow: { display: 'flex', alignItems: 'center', gap: 8 },
  previewBtn: {
    padding: '5px 12px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 10,
    fontFamily: theme.font.mono, letterSpacing: '0.03em', flexShrink: 0,
  },
  dot: { width: 7, height: 7, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  title: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 13,
    letterSpacing: '0.1em', textTransform: 'uppercase' as const, color: theme.text.primary,
  },
  subtitle: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, letterSpacing: '0.03em' },
  chips: { display: 'flex', gap: 8, flexWrap: 'wrap' as const, marginTop: 2 },
  chipItem: {
    padding: '4px 10px', borderRadius: 20, background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`, fontFamily: theme.font.mono,
    fontSize: 10, letterSpacing: '0.04em', color: theme.text.secondary, whiteSpace: 'nowrap' as const,
  },
  chipActive: {
    padding: '4px 10px', borderRadius: 20, background: theme.accent.amberGlow,
    border: `1px solid ${theme.border.amber}`, fontFamily: theme.font.mono,
    fontSize: 10, letterSpacing: '0.04em', color: theme.accent.amber, whiteSpace: 'nowrap' as const,
  },
  hint: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, letterSpacing: '0.04em' },
  ragSection: { display: 'flex', flexDirection: 'column', gap: 10 },
  ragActions: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' as const },
  ragPickBtn: {
    padding: '9px 16px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 8, color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.body, fontWeight: 600,
  },
  ragNote: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, letterSpacing: '0.04em' },
};
