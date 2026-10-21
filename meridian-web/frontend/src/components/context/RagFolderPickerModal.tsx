import { useState } from 'react';
import { Modal } from '../common/Modal';
import { TextInput } from '../common';
import { ContextSourceCard } from './ContextSourceCard';
import { LettersPickerPanel } from './LettersPickerPanel';
import { ragFolderToContextSourceViewModel, ragAttachedFolderToContextSourceViewModel } from './contextSourceModel';
import type { RagFolderViewModel, RagAttachedFolderViewModel } from './ragContextTypes';
import type { LetterHit, MeetingLetter } from '../../api/letters';
import styles from './RagFolderPickerModal.module.css';

const RAG_DND_MIME = 'application/x-rag-folder-id';

// Контроллер вкладки «Письма» (совместим с возвратом useMeetingLetters).
export interface LettersTabController {
  results: LetterHit[];
  attached: MeetingLetter[];
  searching?: boolean;
  loading?: boolean;
  error?: string | null;
  query: string;
  setQuery: (value: string) => void;
  search: () => void;
  attach: (hit: LetterHit) => void | Promise<void>;
  detach: (sourceId: number) => void | Promise<void>;
  toggleIncluded: (sourceId: number, included: boolean) => void | Promise<void>;
  updatePriority: (sourceId: number, priority: number) => void | Promise<void>;
}

interface RagFolderPickerModalProps {
  open: boolean;
  onClose: () => void;

  enabled: boolean;
  disabledReason?: string;

  folders: RagFolderViewModel[];
  attachedFolders: RagAttachedFolderViewModel[];

  loading?: boolean;
  refreshing?: boolean;
  error?: string | null;

  query: string;
  onQueryChange: (value: string) => void;
  onRefresh: () => void;

  onAttachFolder: (folderId: string) => void | Promise<void>;
  onDetachFolder: (sourceId: string) => void | Promise<void>;
  onToggleIncluded: (sourceId: string, included: boolean) => void | Promise<void>;
  onPriorityChange: (sourceId: string, priority: number) => void | Promise<void>;

  // Вкладка «Письма» — если передан контроллер, в модалке появляются вкладки.
  letters?: LettersTabController;
}

type PickerTab = 'folders' | 'letters';

export function RagFolderPickerModal(props: RagFolderPickerModalProps) {
  const {
    open, onClose, enabled, disabledReason, folders, attachedFolders,
    loading, refreshing, error, query, onQueryChange, onRefresh,
    onAttachFolder, onDetachFolder, onToggleIncluded, onPriorityChange,
    letters,
  } = props;

  const [tab, setTab] = useState<PickerTab>('folders');

  if (!open) return null;

  const attachedByFolder = new Set(attachedFolders.map((s) => s.folderId));

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    if (!enabled) return;
    const folderId = e.dataTransfer.getData(RAG_DND_MIME);
    if (folderId) void onAttachFolder(folderId);
  }

  return (
    <Modal open={open} onClose={onClose} maxWidth={820}>
      <div className={styles.headerRow}>
        <span className={styles.title}>
          {letters && tab === 'letters' ? 'Письма PayHub в контекст' : 'RAG-папки в контекст'}
        </span>
        <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Закрыть">✕</button>
      </div>

      {letters && (
        <div className={styles.tabBar} role="tablist">
          <button
            type="button" role="tab" aria-selected={tab === 'folders'}
            className={tab === 'folders' ? styles.tabActive : styles.tab}
            onClick={() => setTab('folders')}
          >
            RAG-папки
          </button>
          <button
            type="button" role="tab" aria-selected={tab === 'letters'}
            className={tab === 'letters' ? styles.tabActive : styles.tab}
            onClick={() => setTab('letters')}
          >
            Письма {letters.attached.length > 0 ? `(${letters.attached.length})` : ''}
          </button>
        </div>
      )}

      {letters && tab === 'letters' ? (
        <LettersPickerPanel
          results={letters.results}
          attached={letters.attached}
          searching={letters.searching}
          loading={letters.loading}
          error={letters.error}
          query={letters.query}
          onQueryChange={letters.setQuery}
          onSearch={letters.search}
          onAttach={letters.attach}
          onDetach={letters.detach}
          onToggleIncluded={letters.toggleIncluded}
          onPriorityChange={letters.updatePriority}
        />
      ) : (
      <>
      <div className={styles.toolbar}>
        <TextInput
          className={styles.searchWrap}
          inputClassName={styles.search}
          clearLabel="поиск"
          onClear={() => onQueryChange('')}
          aria-label="Поиск по RAG-папкам"
          placeholder="Поиск по RAG-папкам"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && enabled) onRefresh(); }}
          disabled={!enabled}
        />
        <button type="button" className={styles.refreshBtn} onClick={onRefresh} disabled={!enabled || refreshing}>
          {refreshing ? 'Обновление…' : 'Обновить'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={`context-columns ${styles.columns}`}>
        {/* Доступные папки */}
        <div className={styles.zone}>
          <div className={styles.zoneTitle}>Доступные папки</div>
          {!enabled ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyTitle}>RAG-папки ещё не подключены</div>
              <div className={styles.emptyHint}>
                {disabledReason ? `${disabledReason}. ` : ''}
                На следующем этапе сюда подключится список папок из базы знаний.
              </div>
            </div>
          ) : loading ? (
            <div className={styles.muted}>Загрузка папок…</div>
          ) : folders.length === 0 ? (
            <div className={styles.muted}>Папки не найдены.</div>
          ) : (
            <div className={styles.list}>
              {folders.map((f) => {
                const attached = attachedByFolder.has(f.id);
                const draggable = enabled && f.disabled !== true && !attached;
                return (
                  <div
                    key={f.id}
                    draggable={draggable}
                    onDragStart={(e) => { if (draggable) e.dataTransfer.setData(RAG_DND_MIME, f.id); }}
                    className={draggable ? styles.draggable : undefined}
                  >
                    <ContextSourceCard
                      source={ragFolderToContextSourceViewModel(f, attached)}
                      compact
                      right={attached ? <span className={styles.attachedBadge}>уже в контексте</span> : undefined}
                      primaryActionLabel={attached ? undefined : 'В контекст'}
                      onPrimaryAction={attached || f.disabled ? undefined : () => onAttachFolder(f.id)}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Контекст встречи (drop-зона) */}
        <div className={styles.zone}>
          <div className={styles.zoneTitle}>Контекст встречи</div>
          <div
            className={`${styles.dropZone} ${enabled ? '' : styles.dropZoneDisabled}`}
            onDragOver={(e) => { if (enabled) e.preventDefault(); }}
            onDrop={onDrop}
          >
            {attachedFolders.length === 0 ? (
              <div className={styles.emptyState}>
                <div className={styles.emptyTitle}>Перетащите RAG-папку сюда</div>
                <div className={styles.emptyHint}>Или нажмите «В контекст» у нужной папки</div>
              </div>
            ) : (
              <div className={styles.list}>
                {attachedFolders.map((s) => (
                  <ContextSourceCard
                    key={s.sourceId}
                    source={ragAttachedFolderToContextSourceViewModel(s)}
                    compact
                    onToggleIncluded={() => onToggleIncluded(s.sourceId, !s.included)}
                    onPriorityChange={(p) => onPriorityChange(s.sourceId, p)}
                    onRemove={() => onDetachFolder(s.sourceId)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      </>
      )}
    </Modal>
  );
}
