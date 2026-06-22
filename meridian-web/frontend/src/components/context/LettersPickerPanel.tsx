import { theme } from '../../styles/theme';
import { ContextSourceCard } from './ContextSourceCard';
import { letterHitToContextSourceViewModel, attachedLetterToContextSourceViewModel } from './contextSourceModel';
import type { LetterHit, MeetingLetter } from '../../api/letters';

export interface LettersPickerPanelProps {
  results: LetterHit[];
  attached: MeetingLetter[];

  searching?: boolean;
  loading?: boolean;
  error?: string | null;

  query: string;
  onQueryChange: (value: string) => void;
  onSearch: () => void;

  onAttach: (hit: LetterHit) => void | Promise<void>;
  onDetach: (sourceId: number) => void | Promise<void>;
  onToggleIncluded: (sourceId: number, included: boolean) => void | Promise<void>;
  onPriorityChange: (sourceId: number, priority: number) => void | Promise<void>;
}

// Панель ручного выбора писем PayHub: слева — найденные по запросу, справа — прикреплённые
// к встрече. Используется как вкладка внутри RagFolderPickerModal.
export function LettersPickerPanel(props: LettersPickerPanelProps) {
  const {
    results, attached, searching, error,
    query, onQueryChange, onSearch,
    onAttach, onDetach, onToggleIncluded, onPriorityChange,
  } = props;

  const attachedChunks = new Set(attached.map((a) => a.chunkId));

  return (
    <>
      <div style={styles.toolbar}>
        <input
          style={styles.search}
          aria-label="Поиск по письмам PayHub"
          placeholder="Поиск по письмам PayHub — тема, номер, текст…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') onSearch(); }}
        />
        <button type="button" style={styles.searchBtn} onClick={onSearch} disabled={searching || !query.trim()}>
          {searching ? 'Поиск…' : 'Найти'}
        </button>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      <div className="context-columns" style={styles.columns}>
        {/* Найденные письма */}
        <div style={styles.zone}>
          <div style={styles.zoneTitle}>Найденные письма</div>
          {searching ? (
            <div style={styles.muted}>Идёт поиск…</div>
          ) : results.length === 0 ? (
            <div style={styles.emptyState}>
              <div style={styles.emptyTitle}>Введите запрос и нажмите «Найти»</div>
              <div style={styles.emptyHint}>Поиск идёт по переписке PayHub (тема, реестровый номер, текст).</div>
            </div>
          ) : (
            <div style={styles.list}>
              {results.map((hit) => {
                const attachedAlready = attachedChunks.has(hit.chunkId);
                return (
                  <ContextSourceCard
                    key={hit.chunkId}
                    source={letterHitToContextSourceViewModel(hit, attachedAlready)}
                    compact
                    right={attachedAlready ? <span style={styles.attachedBadge}>уже в контексте</span> : undefined}
                    primaryActionLabel={attachedAlready ? undefined : 'В контекст'}
                    onPrimaryAction={attachedAlready ? undefined : () => onAttach(hit)}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* Прикреплённые к встрече */}
        <div style={styles.zone}>
          <div style={styles.zoneTitle}>Контекст встречи</div>
          <div style={styles.attachedZone}>
            {attached.length === 0 ? (
              <div style={styles.emptyState}>
                <div style={styles.emptyTitle}>Письма не выбраны</div>
                <div style={styles.emptyHint}>Нажмите «В контекст» у нужного письма слева.</div>
              </div>
            ) : (
              <div style={styles.list}>
                {attached.map((m) => (
                  <ContextSourceCard
                    key={m.sourceId}
                    source={attachedLetterToContextSourceViewModel(m)}
                    compact
                    onToggleIncluded={() => onToggleIncluded(m.sourceId, !m.included)}
                    onPriorityChange={(p) => onPriorityChange(m.sourceId, p)}
                    onRemove={() => onDetach(m.sourceId)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

const styles: Record<string, React.CSSProperties> = {
  toolbar: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' as const },
  search: {
    flex: 1, minWidth: 160, padding: '9px 12px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary,
    fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  searchBtn: {
    padding: '9px 14px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono,
  },
  columns: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 },
  zone: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 },
  zoneTitle: {
    fontFamily: theme.font.mono, fontSize: 10, fontWeight: 600, letterSpacing: '0.1em',
    textTransform: 'uppercase' as const, color: theme.accent.amber,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  attachedZone: {
    display: 'flex', flexDirection: 'column', gap: 8, minHeight: 120,
    padding: 12, borderRadius: 10, border: `1.5px dashed ${theme.border.default}`,
    background: theme.bg.tertiary,
  },
  emptyState: {
    display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center',
    textAlign: 'center' as const, padding: '20px 12px',
  },
  emptyTitle: { fontSize: 13, color: theme.text.secondary, fontWeight: 600 },
  emptyHint: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, lineHeight: 1.5 },
  muted: { fontFamily: theme.font.mono, fontSize: 12, color: theme.text.muted },
  attachedBadge: {
    padding: '3px 9px', border: `1px solid ${theme.accent.green}`, borderRadius: 10,
    fontFamily: theme.font.mono, fontSize: 9, color: theme.accent.green, whiteSpace: 'nowrap' as const,
  },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
};
