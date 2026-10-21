import { useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import type { WSMessageToServer } from '../../types';
import styles from './ProductionCutoverPanel.module.css';

interface Props {
  meetingId: number | null;
  canEdit?: boolean;
  sendJSON: (message: WSMessageToServer) => void;
}

const REASON_LABELS: Record<string, string> = {
  live_not_streaming: 'live-сессия не в эфире',
  too_few_channels: 'недостаточно каналов',
  too_few_final_segments: 'мало финальных сегментов',
  secondary_too_silent: 'второй канал слишком тих',
  poor_clock_quality: 'плохая синхронизация часов',
  low_match_ratio: 'низкое совпадение с основным',
};

const ROLLOUT_LABELS: Record<string, string> = {
  feature_disabled: 'функция выключена',
  not_in_rollout: 'встреча вне canary-раскатки',
  allowlist_meeting: 'встреча в allowlist',
  allowlist_user: 'пользователь в allowlist',
  rollout_full: 'раскатка 100%',
  rollout_bucket: 'в пределах процента раскатки',
};

export function ProductionCutoverPanel({ meetingId, canEdit = true, sendJSON }: Props) {
  const authority = useMeetingStore((s) => s.transcriptionAuthority);
  const authError = useMeetingStore((s) => s.transcriptionAuthorityError);
  const liveState = useMeetingStore((s) => s.multiChannelLiveState);
  const [force, setForce] = useState(false);

  if (!meetingId) {
    return <div className={styles.note}>Откройте встречу, чтобы управлять источником транскрипта.</div>;
  }
  if (!authority) {
    return <div className={styles.note}>Состояние источника транскрипта загружается…</div>;
  }

  const isMulti = authority.current_source === 'multi_channel';
  const liveActive = liveState?.status === 'streaming' || liveState?.status === 'degraded';
  const quality = authority.quality;
  const rollout = authority.rollout;

  function onPromote() {
    if (!canEdit) return;
    sendJSON({ type: 'transcription_promote', force });
  }
  function onFallback() {
    if (!canEdit) return;
    sendJSON({ type: 'transcription_fallback' });
  }

  return (
    <div className={styles.panel}>
      <div className={styles.note}>
        Авторитетный источник транскрипта встречи. Single STT всегда работает как горячий
        резерв. Перевод на multi-channel — только вручную; авто-перевода нет.
      </div>

      <div className={styles.row}>
        <span className={styles.rowLabel}>Текущий источник</span>
        <span className={isMulti ? styles.badgeMulti : styles.badgeSingle}>
          {isMulti ? 'MULTI-CHANNEL' : 'SINGLE STT'}
        </span>
        {authority.fallback_used && (
          <span className={styles.fallbackTag} title="Был автоматический откат на single">
            был авто-fallback
          </span>
        )}
      </div>

      <div className={styles.metaRow}>
        <span className={styles.rowMeta}>эпох: {authority.epochs_count}</span>
        <span className={styles.rowMeta}>rev: {authority.revision}</span>
        <span className={styles.rowMeta}>
          раскатка: {rollout.allowed ? 'доступна' : 'недоступна'}
          {' '}({ROLLOUT_LABELS[rollout.reason] || rollout.reason})
        </span>
      </div>

      {quality && (
        <div className={styles.qualityBox}>
          <span className={styles.rowMeta}>
            качество: {(quality.score * 100).toFixed(0)}% {quality.ok ? '✓' : '✕'}
          </span>
          {quality.reasons.length > 0 && (
            <div className={styles.reasons}>
              {quality.reasons.map((r) => (
                <span key={r} className={styles.reasonTag}>{REASON_LABELS[r] || r}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {!isMulti && (
        <div className={styles.actions}>
          {!quality?.ok && (
            <label className={styles.forceLabel}>
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
              форсировать (игнорировать quality-gate)
            </label>
          )}
          <button
            className={authority.can_promote && liveActive && canEdit ? styles.btnPromote : styles.btnDisabled}
            disabled={!authority.can_promote || !liveActive || !canEdit}
            onClick={onPromote}
            title={!liveActive ? 'Нужна активная live multi-channel сессия' : ''}
          >
            Перевести на multi-channel
          </button>
          {!liveActive && (
            <span className={styles.hint}>Сначала запустите live multi-channel STT.</span>
          )}
        </div>
      )}

      {isMulti && (
        <div className={styles.actions}>
          <button
            className={canEdit ? styles.btnFallback : styles.btnDisabled}
            disabled={!canEdit}
            onClick={onFallback}
          >
            Откатить на single STT
          </button>
        </div>
      )}

      {authError && (
        <div className={styles.error}>
          {authError.code ? `[${authError.code}] ` : ''}{authError.message || 'Ошибка'}
        </div>
      )}
    </div>
  );
}
