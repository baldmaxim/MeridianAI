import type { FC } from 'react';
import type { FinalizationStatus, MeetingListItem } from '../../types';
import { meetingDisplayName } from '../../lib/meetingName';
import { FIN_LABELS, formatDuration } from '../../lib/meetingMeta';
import { paths, navTo } from '../../lib/navigation';
import { NEGOTIATION_TYPE_LABELS } from '../meetingDetail/meetingDetailFormat';
import { formatDate, formatTime } from './historyFormat';
import styles from './MeetingCard.module.css';

interface IMeetingCardProps {
  meeting: MeetingListItem;
  selected: boolean;
  finalizing: boolean;
  onToggleSelect: (id: number) => void;
  onOpen: (id: number) => void;
  onFinalize: (id: number) => void;
  onRetry: (id: number) => void;
}

/** Тон бейджа статуса протокола (см. MeetingCard.module.css). */
const finTone = (s: FinalizationStatus): string =>
  s === 'completed' ? styles.finCompleted
    : s === 'error' ? styles.finError
      : s === 'partial' ? styles.finPartial
        : styles.finDefault;

/** Строка списка: чекбокс выбора, карточка встречи, кнопки «завершить»/«повторить протокол». */
export const MeetingCard: FC<IMeetingCardProps> = ({
  meeting: m, selected, finalizing, onToggleSelect, onOpen, onFinalize, onRetry,
}) => (
  <div className={styles.row}>
    {/* Checkbox */}
    <label
      className={`${styles.checkWrap}${selected ? ` ${styles.checkWrapSelected}` : ''}`}
      onClick={(e) => e.stopPropagation()}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={() => onToggleSelect(m.id)}
        className={styles.hiddenInput}
      />
      <span className={`${styles.checkbox}${selected ? ` ${styles.checkboxSelected}` : ''}`}>
        {selected && <span className={styles.checkmark}>&#10003;</span>}
      </span>
    </label>
    {/* Card */}
    <button
      className={`${styles.card}${selected ? ` ${styles.cardSelected}` : ''}`}
      {...navTo(paths.meetingDetail(m.id), () => onOpen(m.id))}
    >
      <div className={styles.cardTop}>
        <div className={styles.cardTitle}>{meetingDisplayName(m)}</div>
        <div className={styles.cardDate}>
          {formatDate(m.started_at)} &middot; {formatTime(m.started_at)}
        </div>
      </div>

      {m.meeting_topic && (
        <div className={styles.cardTopic}>{m.meeting_topic}</div>
      )}

      {(m.customer_name || m.object_name) && (
        <div className={styles.cardDir}>
          {m.customer_name && <span className={styles.dirChip}>🏢 {m.customer_name}</span>}
          {m.object_name && <span className={styles.dirChip}>📍 {m.object_name}</span>}
        </div>
      )}

      {m.micro_summary && <div className={styles.cardTopic}>{m.micro_summary}</div>}

      {m.tags && m.tags.length > 0 && (
        <div className={styles.cardDir}>
          {m.tags.map((t) => <span key={t} className={styles.tagChip}>#{t}</span>)}
        </div>
      )}

      <div className={styles.cardBadges}>
        {m.finalization_status && m.finalization_status !== 'not_started' && (
          <span className={`${styles.finBadge} ${finTone(m.finalization_status)}`}>
            {FIN_LABELS[m.finalization_status] || m.finalization_status}
          </span>
        )}
        {m.negotiation_type && (
          <span className={`${styles.badge} ${styles.badgeAmber}`}>
            {NEGOTIATION_TYPE_LABELS[m.negotiation_type] || m.negotiation_type}
          </span>
        )}
        <span className={`${styles.badge} ${styles.badgeBlue}`}>{m.segment_count} сегм.</span>
        <span className={`${styles.badge} ${styles.badgeGreen}`}>{m.suggestion_count} подск.</span>
        <span className={`${styles.badge} ${styles.badgeMuted}`}>{formatDuration(m.recorded_seconds)}</span>
      </div>
    </button>
    {m.status === 'active' && (
      <button
        className={`t-btn t-btn-green ${styles.sideBtn} ${styles.finalizeSide}`}
        onClick={() => onFinalize(m.id)}
        disabled={finalizing}
        title="Завершить встречу"
      >
        {finalizing ? '…' : '✓'}
      </button>
    )}
    {m.finalization_status === 'error' && (
      <button
        className={`t-btn t-btn-red ${styles.sideBtn} ${styles.retrySide}`}
        onClick={() => onRetry(m.id)}
        title="Повторить формирование протокола"
      >
        ↻
      </button>
    )}
  </div>
);
