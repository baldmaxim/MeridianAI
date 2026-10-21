import { TextInput } from '../common';
import { ContextSourceCard } from './ContextSourceCard';
import { letterHitToContextSourceViewModel, attachedLetterToContextSourceViewModel } from './contextSourceModel';
import type { LetterHit, MeetingLetter } from '../../api/letters';
import styles from './LettersPickerPanel.module.css';

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
      <div className={styles.toolbar}>
        <TextInput
          className={styles.searchWrap}
          inputClassName={styles.search}
          clearLabel="поиск"
          onClear={() => onQueryChange('')}
          aria-label="Поиск по письмам PayHub"
          placeholder="Поиск по письмам PayHub — тема, номер, текст…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') onSearch(); }}
        />
        <button type="button" className={styles.searchBtn} onClick={onSearch} disabled={searching || !query.trim()}>
          {searching ? 'Поиск…' : 'Найти'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={`context-columns ${styles.columns}`}>
        {/* Найденные письма */}
        <div className={styles.zone}>
          <div className={styles.zoneTitle}>Найденные письма</div>
          {searching ? (
            <div className={styles.muted}>Идёт поиск…</div>
          ) : results.length === 0 ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyTitle}>Введите запрос и нажмите «Найти»</div>
              <div className={styles.emptyHint}>Поиск идёт по переписке PayHub (тема, реестровый номер, текст).</div>
            </div>
          ) : (
            <div className={styles.list}>
              {results.map((hit) => {
                const attachedAlready = attachedChunks.has(hit.chunkId);
                return (
                  <ContextSourceCard
                    key={hit.chunkId}
                    source={letterHitToContextSourceViewModel(hit, attachedAlready)}
                    compact
                    right={attachedAlready ? <span className={styles.attachedBadge}>уже в контексте</span> : undefined}
                    primaryActionLabel={attachedAlready ? undefined : 'В контекст'}
                    onPrimaryAction={attachedAlready ? undefined : () => onAttach(hit)}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* Прикреплённые к встрече */}
        <div className={styles.zone}>
          <div className={styles.zoneTitle}>Контекст встречи</div>
          <div className={styles.attachedZone}>
            {attached.length === 0 ? (
              <div className={styles.emptyState}>
                <div className={styles.emptyTitle}>Письма не выбраны</div>
                <div className={styles.emptyHint}>Нажмите «В контекст» у нужного письма слева.</div>
              </div>
            ) : (
              <div className={styles.list}>
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
