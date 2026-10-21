import { useCallback, useEffect, useState } from 'react';
import { Modal } from '../common/Modal';
import { Select, TextInput } from '../common';
import { apiErrorMessage } from '../../lib/apiError';
import styles from './ContextPreviewModal.module.css';
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

function statusClass(b: ContextBlockPreview): string {
  if (!b.enabled) return styles.statusOff;
  if (b.truncated) return styles.statusTrunc;
  return styles.statusOn;
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
      <div className={styles.headerRow}>
        <span className={styles.title}>Предпросмотр контекста для ИИ</span>
        <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Закрыть">✕</button>
      </div>
      <div className={styles.note}>
        Это не запрос к LLM. Здесь показано, какие блоки контекста будут переданы в подсказки.
      </div>

      {meetingId == null ? (
        <div className={styles.emptyState}>
          <div className={styles.emptyTitle}>Сначала создайте встречу или добавьте файл/контекст</div>
          <div className={styles.emptyHint}>Предпросмотр доступен, когда встреча подготовлена.</div>
        </div>
      ) : (
        <>
          <div className={styles.toolbar}>
            <Select
              triggerClassName={styles.select}
              ariaLabel="Режим подсказки"
              value={mode}
              onChange={(v) => setMode(v as ContextPreviewMode)}
              options={MODE_OPTIONS}
            />
            <TextInput
              className={styles.searchWrap}
              inputClassName={styles.search}
              clearLabel="запрос"
              onClear={() => setQuery('')}
              aria-label="Проверить по вопросу или теме"
              placeholder="Проверить по вопросу / теме"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void load(); }}
            />
            <button type="button" className={styles.refreshBtn} onClick={() => void load()} disabled={loading}>
              {loading ? 'Обновление…' : 'Обновить'}
            </button>
          </div>

          {error && <div className={styles.error}>{error}</div>}

          {pack && (
            <>
              <div className={styles.summary}>
                <span className={styles.summaryItem}>Всего: {pack.total_chars} символов</span>
                <span className={styles.summaryItem}>≈ {pack.estimated_tokens} токенов</span>
                {pack.max_chars != null && <span className={styles.summaryItem}>Лимит: {pack.max_chars}</span>}
                {pack.truncated && <span className={styles.summaryTrunc}>часть контекста обрезана</span>}
              </div>

              <div className={styles.list}>
                {pack.blocks.map((b) => (
                  <div key={b.kind} className={`${styles.block} ${b.enabled ? '' : styles.blockDisabled}`}>
                    <div className={styles.blockHead}>
                      <span className={styles.blockTitle}>{b.title}</span>
                      <span className={styles.kindBadge}>{b.kind}</span>
                      <span className={`${styles.statusDot} ${statusClass(b)}`} />
                      <span className={styles.blockState}>{b.enabled ? 'включён' : 'выключен'}</span>
                      <span className={styles.spacer} />
                      {b.truncated && <span className={styles.truncBadge}>обрезан</span>}
                    </div>
                    <div className={styles.blockMeta}>
                      {b.chars} симв. · ≈ {b.estimated_tokens} ток.
                      {b.source_count > 0 && <> · источников: {b.source_count}</>}
                      {b.max_chars != null && <> · лимит {b.max_chars}</>}
                    </div>
                    {b.reason && <div className={styles.reason}>{b.reason}</div>}
                    {b.enabled && b.content_preview && (
                      <pre className={styles.preview}>{b.content_preview}</pre>
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
