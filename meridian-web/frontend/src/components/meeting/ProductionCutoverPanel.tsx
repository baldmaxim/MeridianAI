import { useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import type { WSMessageToServer } from '../../types';

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
    return <div style={styles.note}>Откройте встречу, чтобы управлять источником транскрипта.</div>;
  }
  if (!authority) {
    return <div style={styles.note}>Состояние источника транскрипта загружается…</div>;
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
    <div style={styles.panel}>
      <div style={styles.note}>
        Авторитетный источник транскрипта встречи. Single STT всегда работает как горячий
        резерв. Перевод на multi-channel — только вручную; авто-перевода нет.
      </div>

      <div style={styles.row}>
        <span style={styles.rowLabel}>Текущий источник</span>
        <span style={isMulti ? styles.badgeMulti : styles.badgeSingle}>
          {isMulti ? 'MULTI-CHANNEL' : 'SINGLE STT'}
        </span>
        {authority.fallback_used && (
          <span style={styles.fallbackTag} title="Был автоматический откат на single">
            был авто-fallback
          </span>
        )}
      </div>

      <div style={styles.metaRow}>
        <span style={styles.rowMeta}>эпох: {authority.epochs_count}</span>
        <span style={styles.rowMeta}>rev: {authority.revision}</span>
        <span style={styles.rowMeta}>
          раскатка: {rollout.allowed ? 'доступна' : 'недоступна'}
          {' '}({ROLLOUT_LABELS[rollout.reason] || rollout.reason})
        </span>
      </div>

      {quality && (
        <div style={styles.qualityBox}>
          <span style={styles.rowMeta}>
            качество: {(quality.score * 100).toFixed(0)}% {quality.ok ? '✓' : '✕'}
          </span>
          {quality.reasons.length > 0 && (
            <div style={styles.reasons}>
              {quality.reasons.map((r) => (
                <span key={r} style={styles.reasonTag}>{REASON_LABELS[r] || r}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {!isMulti && (
        <div style={styles.actions}>
          {!quality?.ok && (
            <label style={styles.forceLabel}>
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
              форсировать (игнорировать quality-gate)
            </label>
          )}
          <button
            style={authority.can_promote && liveActive && canEdit ? styles.btnPromote : styles.btnDisabled}
            disabled={!authority.can_promote || !liveActive || !canEdit}
            onClick={onPromote}
            title={!liveActive ? 'Нужна активная live multi-channel сессия' : ''}
          >
            Перевести на multi-channel
          </button>
          {!liveActive && (
            <span style={styles.hint}>Сначала запустите live multi-channel STT.</span>
          )}
        </div>
      )}

      {isMulti && (
        <div style={styles.actions}>
          <button
            style={canEdit ? styles.btnFallback : styles.btnDisabled}
            disabled={!canEdit}
            onClick={onFallback}
          >
            Откатить на single STT
          </button>
        </div>
      )}

      {authError && (
        <div style={styles.error}>
          {authError.code ? `[${authError.code}] ` : ''}{authError.message || 'Ошибка'}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  panel: { display: 'flex', flexDirection: 'column', gap: 10 },
  note: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, lineHeight: 1.5 },
  row: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  metaRow: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' },
  rowLabel: { fontFamily: theme.font.body, fontSize: 13, color: theme.text.primary },
  rowMeta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  badgeSingle: {
    fontFamily: theme.font.mono, fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
    color: theme.accent.blue, background: 'rgba(91,156,246,0.12)', padding: '3px 8px', borderRadius: 6,
  },
  badgeMulti: {
    fontFamily: theme.font.mono, fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
    color: theme.accent.green, background: 'rgba(46,229,157,0.12)', padding: '3px 8px', borderRadius: 6,
  },
  fallbackTag: {
    fontFamily: theme.font.mono, fontSize: 10, color: theme.accent.amber,
    background: 'rgba(245,166,35,0.12)', padding: '2px 6px', borderRadius: 6,
  },
  qualityBox: {
    display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 10px',
    background: theme.bg.input, borderRadius: 8,
  },
  reasons: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  reasonTag: {
    fontFamily: theme.font.mono, fontSize: 10, color: theme.accent.red,
    background: 'rgba(255,75,110,0.10)', padding: '2px 6px', borderRadius: 6,
  },
  actions: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' },
  forceLabel: {
    fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary,
    display: 'flex', alignItems: 'center', gap: 6,
  },
  btnPromote: {
    fontFamily: theme.font.body, fontSize: 13, color: '#080A0F', background: theme.accent.green,
    border: 'none', borderRadius: 8, padding: '8px 14px', cursor: 'pointer', fontWeight: 600,
  },
  btnFallback: {
    fontFamily: theme.font.body, fontSize: 13, color: theme.text.primary, background: theme.bg.elevated,
    border: `1px solid ${theme.accent.amber}`, borderRadius: 8, padding: '8px 14px', cursor: 'pointer',
  },
  btnDisabled: {
    fontFamily: theme.font.body, fontSize: 13, color: theme.text.muted, background: theme.bg.input,
    border: 'none', borderRadius: 8, padding: '8px 14px', cursor: 'not-allowed',
  },
  hint: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  error: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.red, lineHeight: 1.5 },
};
