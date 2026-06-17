import { useCallback, useEffect, useState } from 'react';
import { Modal } from '../common/Modal';
import { theme } from '../../styles/theme';
import { apiErrorMessage } from '../../lib/apiError';
import {
  getMeetingContextPreview,
  type ContextPackPreview, type ContextPreviewMode, type ContextBlockPreview,
} from '../../api/contextPreview';

interface ContextPreviewModalProps {
  open: boolean;
  onClose: () => void;
  meetingId: number | null;
}

const MODE_OPTIONS: { value: ContextPreviewMode; label: string }[] = [
  { value: 'auto', label: 'Авто-подсказка' },
  { value: 'manual', label: 'Ручная подсказка' },
  { value: 'strengthen', label: 'Усиление позиции' },
];

function statusColor(b: ContextBlockPreview): string {
  if (!b.enabled) return theme.text.muted;
  if (b.truncated) return theme.accent.amber;
  return theme.accent.green;
}

export function ContextPreviewModal({ open, onClose, meetingId }: ContextPreviewModalProps) {
  const [mode, setMode] = useState<ContextPreviewMode>('manual');
  const [query, setQuery] = useState('');
  const [pack, setPack] = useState<ContextPackPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (meetingId == null) return;
    setLoading(true);
    setError(null);
    try {
      setPack(await getMeetingContextPreview(meetingId, { mode, q: query || undefined }));
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось загрузить предпросмотр контекста'));
    } finally {
      setLoading(false);
    }
  }, [meetingId, mode, query]);

  // Автозагрузка при открытии / смене режима. Запрос только если встреча есть.
  useEffect(() => {
    if (open && meetingId != null) void load();
    if (!open) { setPack(null); setError(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, meetingId]);

  if (!open) return null;

  return (
    <Modal open={open} onClose={onClose} maxWidth={820}>
      <div style={styles.headerRow}>
        <span style={styles.title}>Предпросмотр контекста для ИИ</span>
        <button type="button" style={styles.closeBtn} onClick={onClose} aria-label="Закрыть">✕</button>
      </div>
      <div style={styles.note}>
        Это не запрос к LLM. Здесь показано, какие блоки контекста будут переданы в подсказки.
      </div>

      {meetingId == null ? (
        <div style={styles.emptyState}>
          <div style={styles.emptyTitle}>Сначала создайте встречу или добавьте файл/контекст</div>
          <div style={styles.emptyHint}>Предпросмотр доступен, когда встреча подготовлена.</div>
        </div>
      ) : (
        <>
          <div style={styles.toolbar}>
            <select
              style={styles.select}
              aria-label="Режим подсказки"
              value={mode}
              onChange={(e) => setMode(e.target.value as ContextPreviewMode)}
            >
              {MODE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <input
              style={styles.search}
              aria-label="Проверить по вопросу или теме"
              placeholder="Проверить по вопросу / теме"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void load(); }}
            />
            <button type="button" style={styles.refreshBtn} onClick={() => void load()} disabled={loading}>
              {loading ? 'Обновление…' : 'Обновить'}
            </button>
          </div>

          {error && <div style={styles.error}>{error}</div>}

          {pack && (
            <>
              <div style={styles.summary}>
                <span style={styles.summaryItem}>Всего: {pack.total_chars} символов</span>
                <span style={styles.summaryItem}>≈ {pack.estimated_tokens} токенов</span>
                {pack.max_chars != null && <span style={styles.summaryItem}>Лимит: {pack.max_chars}</span>}
                {pack.truncated && <span style={styles.summaryTrunc}>часть контекста обрезана</span>}
              </div>

              <div style={styles.list}>
                {pack.blocks.map((b) => (
                  <div key={b.kind} style={{ ...styles.block, ...(b.enabled ? {} : styles.blockDisabled) }}>
                    <div style={styles.blockHead}>
                      <span style={styles.blockTitle}>{b.title}</span>
                      <span style={styles.kindBadge}>{b.kind}</span>
                      <span style={{ ...styles.statusDot, background: statusColor(b) }} />
                      <span style={styles.blockState}>{b.enabled ? 'включён' : 'выключен'}</span>
                      <span style={{ flex: 1 }} />
                      {b.truncated && <span style={styles.truncBadge}>обрезан</span>}
                    </div>
                    <div style={styles.blockMeta}>
                      {b.chars} симв. · ≈ {b.estimated_tokens} ток.
                      {b.source_count > 0 && <> · источников: {b.source_count}</>}
                      {b.max_chars != null && <> · лимит {b.max_chars}</>}
                    </div>
                    {b.reason && <div style={styles.reason}>{b.reason}</div>}
                    {b.enabled && b.content_preview && (
                      <pre style={styles.preview}>{b.content_preview}</pre>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
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
  note: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, lineHeight: 1.5 },
  toolbar: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' as const },
  select: {
    padding: '9px 12px', background: theme.bg.input, border: `1px solid ${theme.border.default}`,
    borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  search: {
    flex: 1, minWidth: 160, padding: '9px 12px', background: theme.bg.input,
    border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary,
    fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  refreshBtn: {
    padding: '9px 14px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono,
  },
  summary: { display: 'flex', gap: 12, flexWrap: 'wrap' as const, alignItems: 'center' },
  summaryItem: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary },
  summaryTrunc: {
    fontFamily: theme.font.mono, fontSize: 10, color: theme.accent.amber,
    padding: '3px 9px', border: `1px solid ${theme.border.amber}`, borderRadius: 10,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 10 },
  block: {
    display: 'flex', flexDirection: 'column', gap: 6, padding: 12, borderRadius: 10,
    background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`,
  },
  blockDisabled: { opacity: 0.55 },
  blockHead: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const },
  blockTitle: { fontSize: 13, fontWeight: 600, color: theme.text.primary },
  kindBadge: {
    fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted,
    padding: '2px 7px', border: `1px solid ${theme.border.default}`, borderRadius: 8,
  },
  statusDot: { width: 7, height: 7, borderRadius: '50%', flexShrink: 0 },
  blockState: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.secondary },
  truncBadge: {
    fontFamily: theme.font.mono, fontSize: 9, color: theme.accent.amber,
    padding: '2px 7px', border: `1px solid ${theme.border.amber}`, borderRadius: 8,
  },
  blockMeta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  reason: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.secondary },
  preview: {
    margin: 0, padding: 10, background: theme.bg.input, borderRadius: 8,
    border: `1px solid ${theme.border.default}`, color: theme.text.secondary,
    fontFamily: theme.font.mono, fontSize: 11, lineHeight: 1.5,
    whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const,
    maxHeight: 200, overflow: 'auto',
  },
  emptyState: {
    display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center',
    textAlign: 'center' as const, padding: '28px 12px',
  },
  emptyTitle: { fontSize: 13, color: theme.text.secondary, fontWeight: 600 },
  emptyHint: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
};
