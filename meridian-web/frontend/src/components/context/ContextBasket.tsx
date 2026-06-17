import { useState } from 'react';
import { theme } from '../../styles/theme';
import { CollapsibleSection } from '../common/CollapsibleSection';
import { MeetingDocuments } from './MeetingDocuments';
import { PreviousMeetingsContext } from './PreviousMeetingsContext';
import { ContextSourceCard } from './ContextSourceCard';
import { ragPlaceholderToContextSourceViewModel, type ContextSourceSectionSummary } from './contextSourceModel';

interface Props {
  meetingId: number | null;
  customerId?: number | null;
  objectId?: number | null;
}

function chip(label: string, s: ContextSourceSectionSummary | null): string {
  if (!s || s.total === 0) return `${label}: 0`;
  return `${label}: ${s.included}/${s.total}`;
}

// Корзина контекста: единая визуальная зона «что попадёт в подсказки».
// Объединяет источники контекста встречи (документы, прошлые встречи, RAG).
export function ContextBasket({ meetingId, customerId, objectId }: Props) {
  const [docSummary, setDocSummary] = useState<ContextSourceSectionSummary | null>(null);
  const [prevSummary, setPrevSummary] = useState<ContextSourceSectionSummary | null>(null);
  const rag = ragPlaceholderToContextSourceViewModel();

  return (
    <div style={styles.wrap}>
      <div style={styles.head}>
        <div style={styles.titleRow}>
          <span style={styles.dot} />
          <span style={styles.title}>Что попадёт в подсказки</span>
        </div>
        <div style={styles.subtitle}>Добавьте документы, прошлые встречи или RAG-папки</div>
        <div style={styles.chips}>
          <span style={styles.chipItem}>{chip('Файлы', docSummary)}</span>
          <span style={styles.chipItem}>{chip('Прошлые встречи', prevSummary)}</span>
          <span style={styles.chipItem}>RAG: скоро</span>
        </div>
      </div>

      <CollapsibleSection title="Файлы" defaultOpen>
        <MeetingDocuments
          meetingId={meetingId}
          customerId={customerId}
          objectId={objectId}
          onSummaryChange={setDocSummary}
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

      <CollapsibleSection title="RAG-папки">
        {/* TODO: connect RAG folder picker; source_type='rag_folder' */}
        <ContextSourceCard
          source={rag}
          primaryActionLabel="Добавить папку"
        />
      </CollapsibleSection>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: { display: 'flex', flexDirection: 'column', gap: 14 },
  head: { display: 'flex', flexDirection: 'column', gap: 6 },
  titleRow: { display: 'flex', alignItems: 'center', gap: 8 },
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
  hint: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, letterSpacing: '0.04em' },
};
