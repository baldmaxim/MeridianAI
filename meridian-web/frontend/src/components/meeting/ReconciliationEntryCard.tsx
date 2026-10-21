import type { FC } from 'react';
import type { MultiChannelReconciliationEntry } from '../../types';
import styles from './MultiChannelReconciliationPanel.module.css';
import tone from './Tone.module.css';

const SIDE_RU = (s: string | null) => s === 'self' ? 'Мы' : s === 'opponent' ? 'Не мы' : '—';

interface IEntryCardProps {
  e: MultiChannelReconciliationEntry; fmt: (ms: number | null) => string; canEdit: boolean;
  busy: boolean; confirming: boolean; selected: boolean;
  onSelect: (v: boolean) => void; onApply: () => void; onConfirmApply: () => void;
  onCancelConfirm: () => void; onDismiss: () => void;
}

export const ReconciliationEntryCard: FC<IEntryCardProps> = (props) => {
  const { e, fmt, canEdit, busy, confirming, selected } = props;
  const statusText = e.kind === 'ambiguous' ? 'Неоднозначное соответствие'
    : e.kind === 'channel_only' ? 'Только в multi-channel'
    : e.kind === 'primary_only' ? 'Только в основном transcript'
    : e.side_agreement === 'suggested' ? `Предлагается: ${SIDE_RU(e.channel_side)}`
    : e.side_agreement === 'confirmed' ? 'Подтверждено каналом'
    : e.side_agreement === 'conflict' ? 'Конфликт сторон' : 'Сторона канала не указана';
  const statusTone = e.side_agreement === 'conflict' ? tone.red
    : e.side_agreement === 'confirmed' ? tone.green
    : e.side_agreement === 'suggested' ? tone.amber : tone.muted;

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        {e.can_apply_side && (
          <input type="checkbox" checked={selected} onChange={(ev) => props.onSelect(ev.target.checked)} />
        )}
        <span className={`${styles.status} ${statusTone}`}>{statusText}</span>
        <span className={styles.spacer} />
        {e.match_score > 0 && <span className={styles.rowMeta}>score {(e.match_score * 100).toFixed(0)}%</span>}
      </div>

      {e.primary_text != null && (
        <div className={styles.side}>
          <div className={styles.sideHead}>основной · {fmt(e.primary_start_server_ms)}
            {e.current_side ? ` · сейчас: ${SIDE_RU(e.current_side)}` : ''}
            {e.has_segment_correction ? ' ✎' : ''}</div>
          <div className={styles.text}>{e.primary_text}</div>
        </div>
      )}
      {e.channel_text != null && (
        <div className={styles.side}>
          <div className={styles.sideHead}>
            канал {(e.channel_index ?? 0) + 1} · {e.channel_label} · {SIDE_RU(e.channel_side)} · {fmt(e.channel_start_server_ms)}
            {e.provider_confidence != null ? ` · ${(e.provider_confidence * 100).toFixed(0)}%` : ''}
          </div>
          <div className={styles.text}>{e.channel_text}</div>
        </div>
      )}
      {e.kind === 'ambiguous' && e.alternatives.length > 0 && (
        <div className={styles.alts}>
          {e.alternatives.map((a) => (
            <div key={a.channel_segment_id} className={styles.rowMeta}>
              канал {a.channel_index + 1}: score {(a.match_score * 100).toFixed(0)}%
            </div>
          ))}
        </div>
      )}
      {e.warnings.map((w, i) => <div key={i} className={styles.warn}>⚠ {w}</div>)}

      <div className={styles.cardActions}>
        {confirming ? (
          <>
            <span className={styles.confirmText}>
              {e.side_agreement === 'conflict'
                ? `У реплики уже задана другая сторона. Заменить на «${SIDE_RU(e.channel_side)}»?`
                : `У реплики уже есть ручная коррекция (метка/заметка сохранятся). Задать сторону «${SIDE_RU(e.channel_side)}»?`}
            </span>
            <button type="button" className={styles.primary} disabled={busy} onClick={props.onConfirmApply}>Заменить</button>
            <button type="button" className={styles.ghost} onClick={props.onCancelConfirm}>Отмена</button>
          </>
        ) : (
          <>
            {e.can_apply_side && canEdit && (
              <button type="button" className={styles.primary} disabled={busy} onClick={props.onApply}>
                Применить сторону канала
              </button>
            )}
            <button type="button" className={styles.ghost} onClick={props.onDismiss}>Скрыть</button>
          </>
        )}
      </div>
    </div>
  );
};
