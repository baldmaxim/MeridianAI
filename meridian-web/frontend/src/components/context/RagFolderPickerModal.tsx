import { Modal } from '../common/Modal';
import { theme } from '../../styles/theme';
import { ContextSourceCard } from './ContextSourceCard';
import { ragFolderToContextSourceViewModel, ragAttachedFolderToContextSourceViewModel } from './contextSourceModel';
import type { RagFolderViewModel, RagAttachedFolderViewModel } from './ragContextTypes';

const RAG_DND_MIME = 'application/x-rag-folder-id';

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
}

export function RagFolderPickerModal(props: RagFolderPickerModalProps) {
  const {
    open, onClose, enabled, disabledReason, folders, attachedFolders,
    loading, refreshing, error, query, onQueryChange, onRefresh,
    onAttachFolder, onDetachFolder, onToggleIncluded, onPriorityChange,
  } = props;

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
      <div style={styles.headerRow}>
        <span style={styles.title}>Добавить RAG-папки в контекст</span>
        <button type="button" style={styles.closeBtn} onClick={onClose} aria-label="Закрыть">✕</button>
      </div>

      <div style={styles.toolbar}>
        <input
          style={styles.search}
          aria-label="Поиск по RAG-папкам"
          placeholder="Поиск по RAG-папкам"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && enabled) onRefresh(); }}
          disabled={!enabled}
        />
        <button type="button" style={styles.refreshBtn} onClick={onRefresh} disabled={!enabled || refreshing}>
          {refreshing ? 'Обновление…' : 'Обновить'}
        </button>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      <div className="context-columns" style={styles.columns}>
        {/* Доступные папки */}
        <div style={styles.zone}>
          <div style={styles.zoneTitle}>Доступные папки</div>
          {!enabled ? (
            <div style={styles.emptyState}>
              <div style={styles.emptyTitle}>RAG-папки ещё не подключены</div>
              <div style={styles.emptyHint}>
                {disabledReason ? `${disabledReason}. ` : ''}
                На следующем этапе сюда подключится список папок из базы знаний.
              </div>
            </div>
          ) : loading ? (
            <div style={styles.muted}>Загрузка папок…</div>
          ) : folders.length === 0 ? (
            <div style={styles.muted}>Папки не найдены.</div>
          ) : (
            <div style={styles.list}>
              {folders.map((f) => {
                const attached = attachedByFolder.has(f.id);
                const draggable = enabled && f.disabled !== true && !attached;
                return (
                  <div
                    key={f.id}
                    draggable={draggable}
                    onDragStart={(e) => { if (draggable) e.dataTransfer.setData(RAG_DND_MIME, f.id); }}
                    style={draggable ? styles.draggable : undefined}
                  >
                    <ContextSourceCard
                      source={ragFolderToContextSourceViewModel(f, attached)}
                      compact
                      right={attached ? <span style={styles.attachedBadge}>уже в контексте</span> : undefined}
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
        <div style={styles.zone}>
          <div style={styles.zoneTitle}>Контекст встречи</div>
          <div
            style={{ ...styles.dropZone, ...(enabled ? {} : styles.dropZoneDisabled) }}
            onDragOver={(e) => { if (enabled) e.preventDefault(); }}
            onDrop={onDrop}
          >
            {attachedFolders.length === 0 ? (
              <div style={styles.emptyState}>
                <div style={styles.emptyTitle}>Перетащите RAG-папку сюда</div>
                <div style={styles.emptyHint}>Или нажмите «В контекст» у нужной папки</div>
              </div>
            ) : (
              <div style={styles.list}>
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
    </Modal>
  );
}

const styles: Record<string, React.CSSProperties> = {
  headerRow: { display: 'flex', alignItems: 'center', gap: 12 },
  title: {
    flex: 1, fontFamily: theme.font.heading, fontWeight: 700, fontSize: 14,
    letterSpacing: '0.06em', textTransform: 'uppercase' as const, color: theme.text.primary,
  },
  closeBtn: {
    width: 30, height: 28, background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 6, color: theme.text.secondary, cursor: 'pointer', fontSize: 13, flexShrink: 0,
  },
  toolbar: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' as const },
  search: {
    flex: 1, minWidth: 160, padding: '9px 12px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary,
    fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  refreshBtn: {
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
  draggable: { cursor: 'grab' },
  dropZone: {
    display: 'flex', flexDirection: 'column', gap: 8, minHeight: 120,
    padding: 12, borderRadius: 10, border: `1.5px dashed ${theme.border.default}`,
    background: theme.bg.tertiary,
  },
  dropZoneDisabled: { opacity: 0.5 },
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
