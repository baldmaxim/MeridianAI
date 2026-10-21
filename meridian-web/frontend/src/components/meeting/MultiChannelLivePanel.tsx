import { useEffect, useMemo, useRef, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import styles from './MultiChannelLivePanel.module.css';
import type {
  IngestTrackInfo, PublicSpeakerSide, WSMessageToServer,
  MultiChannelLiveSegment, MultiChannelLiveStatus,
} from '../../types';

interface Props {
  meetingId: number | null;
  canEdit?: boolean;
  sendJSON: (message: WSMessageToServer) => void;
}

const NON_TERMINAL: MultiChannelLiveStatus[] = ['buffering', 'connecting', 'streaming', 'degraded', 'stopping'];

const STATUS_LABEL: Record<string, string> = {
  idle: 'не запущено', buffering: 'буферизация', connecting: 'подключение',
  streaming: 'идёт распознавание', degraded: 'деградировано', stopping: 'остановка',
  stopped: 'остановлено', failed: 'ошибка',
};

function trackLabel(t: IngestTrackInfo): string {
  if (t.role === 'primary') return 'Основной';
  if (t.side_hint === 'self') return 'Shadow · Мы';
  if (t.side_hint === 'opponent') return 'Shadow · Не мы';
  return 'Shadow · сторона ?';
}

function friendlyError(code?: string | null, message?: string | null): string | null {
  if (!code) return null;
  switch (code) {
    case 'PROVIDER_NOT_CONFIGURED':
    case 'PROVIDER_AUTH': return 'STT-провайдер не настроен';
    case 'PROVIDER_RATE_LIMIT': return 'Лимит STT-провайдера исчерпан. Повторите позже';
    case 'PROVIDER_TIMEOUT': return 'Провайдер не ответил вовремя';
    case 'PROVIDER_DISCONNECTED': return 'Соединение со STT-провайдером потеряно';
    case 'PROVIDER_BACKPRESSURE': return 'Перегрузка отправки в STT';
    case 'MUX_BUFFERING': return 'Недостаточно данных для старта (буферизация)';
    case 'ALIGNMENT_NOT_READY': return 'Каналы ещё не выровнены';
    case 'CLOCK_QUALITY': return 'Качество синхронизации secondary недостаточно';
    case 'TRACK_NOT_FOUND': return 'Канал стал недоступен';
    case 'CONSENT_REQUIRED': return 'Требуется подтверждение согласия';
    case 'FORBIDDEN': return 'Нет права запускать live shadow';
    default: return message || 'Ошибка live multi-channel';
  }
}

function fmtTs(ms: number): string {
  const s = Math.max(0, ms) / 1000;
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${(s - m * 60).toFixed(1).padStart(4, '0')}`;
}

export function MultiChannelLivePanel({ meetingId, canEdit = true, sendJSON }: Props) {
  const isConnected = useMeetingStore((s) => s.isConnected);
  const alignment = useMeetingStore((s) => s.ingestAlignment);
  const liveState = useMeetingStore((s) => s.multiChannelLiveState);
  const finals = useMeetingStore((s) => s.multiChannelLiveFinalSegments);
  const interimByChannel = useMeetingStore((s) => s.multiChannelLiveInterimByChannel);
  const clearLive = useMeetingStore((s) => s.clearMultiChannelLive);

  const tracks = useMemo(() => alignment?.tracks ?? [], [alignment]);
  const byId = useMemo(() => Object.fromEntries(tracks.map((t) => [t.track_id, t])), [tracks]);
  const [selected, setSelected] = useState<string[]>([]);
  const [sideOverrides, setSideOverrides] = useState<Record<string, PublicSpeakerSide | ''>>({});
  const [consent, setConsent] = useState(false);
  const didInit = useRef(false);

  const status = liveState?.status ?? 'idle';
  const active = NON_TERMINAL.includes(status);
  const alignmentReady = alignment != null && alignment.common_lo != null;

  // дефолтный выбор каналов, пока сессия не активна
  useEffect(() => {
    if (active) return;
    if (didInit.current && selected.length) return;
    const withFrames = tracks.filter((t) => t.buffered_frames > 0);
    if (!withFrames.length) return;
    didInit.current = true;
    const primaries = withFrames.filter((t) => t.role === 'primary').map((t) => t.track_id);
    const secondaries = withFrames.filter((t) => t.role === 'secondary')
      .sort((a, b) => (b.last_index ?? 0) - (a.last_index ?? 0));
    const def = [...primaries.slice(0, 1)];
    if (secondaries.length) def.push(secondaries[0].track_id);
    setSelected(def);
    const ov: Record<string, PublicSpeakerSide | ''> = {};
    for (const t of withFrames) {
      ov[t.track_id] = (t.side_hint === 'self' || t.side_hint === 'opponent') ? t.side_hint : '';
    }
    setSideOverrides(ov);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tracks, active]);

  // сброс consent когда сессия не идёт
  useEffect(() => {
    if (!active) setConsent(false);
  }, [active]);

  function toggle(id: string) {
    if (active) return;
    setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
  }
  function move(id: string, dir: -1 | 1) {
    if (active) return;
    setSelected((s) => {
      const i = s.indexOf(id); const j = i + dir;
      if (i < 0 || j < 0 || j >= s.length) return s;
      const n = [...s]; [n[i], n[j]] = [n[j], n[i]]; return n;
    });
  }

  const hasPrimary = selected.some((id) => byId[id]?.role === 'primary');
  const hasSecondary = selected.some((id) => byId[id]?.role === 'secondary');
  const canStart = isConnected && meetingId != null && canEdit && consent
    && selected.length >= 2 && hasPrimary && hasSecondary && alignmentReady && !active;

  function onStart() {
    if (!canStart) return;
    const overrides: Record<string, PublicSpeakerSide | null> = {};
    for (const id of selected) overrides[id] = sideOverrides[id] || null;
    sendJSON({ type: 'multi_channel_live_start', track_ids: selected,
               channel_side_overrides: overrides, consent_confirmed: true });
  }
  function onStop() { sendJSON({ type: 'multi_channel_live_stop' }); }
  function onClear() { sendJSON({ type: 'multi_channel_live_clear' }); clearLive(); }

  function copyCandidate() {
    const text = finals.map((s) => {
      const sd = s.side === 'self' ? 'МЫ' : s.side === 'opponent' ? 'НЕ МЫ' : '·';
      return `[${sd} · Канал ${s.channel_index + 1}] ${s.transcript}`;
    }).join('\n');
    void navigator.clipboard?.writeText(text);
  }
  function downloadJson() {
    const payload = {
      state: liveState, channels: liveState?.channels ?? [], final_segments: finals,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `meridian-meeting-${meetingId}-live-multichannel.json`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  const startMs = liveState?.start_server_ms ?? 0;
  const channels = liveState?.channels ?? [];

  return (
    <div className={styles.panel}>
      <div className={styles.note}>
        Выбранные каналы объединяются в многоканальный поток и отправляются внешнему STT-провайдеру.
      </div>
      <div className={styles.important}>
        Основной transcript и AI-подсказки продолжают использовать текущий STT. Результат ниже —
        только диагностический candidate.
      </div>
      <div className={styles.privacy}>
        Аудио всех выбранных каналов будет передаваться внешнему STT-сервису.
      </div>

      {/* выбор каналов */}
      <div className={styles.section}>каналы (порядок = порядок в потоке)</div>
      <div className={styles.list}>
        {tracks.length === 0 && <div className={styles.dim}>Нет активных источников.</div>}
        {selected.map((id) => byId[id] && (
          <div key={id} className={styles.row}>
            <input type="checkbox" checked readOnly disabled={active} onChange={() => toggle(id)} />
            <span className={styles.rowLabel}>{trackLabel(byId[id])}</span>
            <span className={styles.rowMeta}>
              {(byId[id].buffered_frames * byId[id].frame_ms / 1000).toFixed(1)}с · gaps {byId[id].gaps_count}
            </span>
            <span className={styles.spacer} />
            {(['self', 'opponent', ''] as const).map((sd) => (
              <button key={sd || 'none'} type="button" disabled={active}
                className={sideOverrides[id] === sd ? styles.sideOn : styles.sideOff}
                onClick={() => setSideOverrides((o) => ({ ...o, [id]: sd }))}>
                {sd === 'self' ? 'Мы' : sd === 'opponent' ? 'Не мы' : '?'}
              </button>
            ))}
            <button type="button" className={styles.ord} disabled={active} onClick={() => move(id, -1)}>↑</button>
            <button type="button" className={styles.ord} disabled={active} onClick={() => move(id, 1)}>↓</button>
          </div>
        ))}
        {!active && tracks.filter((t) => !selected.includes(t.track_id)).map((t) => (
          <div key={t.track_id} className={`${styles.row} ${styles.rowDim}`}>
            <input type="checkbox" checked={false} onChange={() => toggle(t.track_id)} />
            <span className={styles.rowLabel}>{trackLabel(t)}</span>
            <span className={styles.rowMeta}>{(t.buffered_frames * t.frame_ms / 1000).toFixed(1)}с</span>
          </div>
        ))}
      </div>

      {!alignmentReady && <div className={styles.warn}>Каналы ещё не выровнены — старт недоступен.</div>}

      <label className={styles.privacyRow}>
        <input type="checkbox" checked={consent} disabled={active}
          onChange={(e) => setConsent(e.target.checked)} />
        <span>Я подтверждаю, что имею право передавать эту запись внешнему STT-сервису</span>
      </label>

      {/* статус */}
      {liveState && status !== 'idle' && (
        <div className={styles.statusRow}>
          <span className={`${styles.badge} ${status === 'failed' ? styles.badgeFailed
            : status === 'streaming' ? styles.badgeStreaming : styles.badgeWarn}`}>
            {STATUS_LABEL[status] ?? status}
          </span>
          {liveState.provider && <span className={styles.rowMeta}>{liveState.provider}/{liveState.model}</span>}
          {status === 'streaming' && (
            <span className={styles.rowMeta}>
              чанков {liveState.chunks_sent ?? 0} · кадров {liveState.frames_sent ?? 0} ·
              {' '}{((liveState.bytes_sent ?? 0) / 1024).toFixed(0)} КБ · очередь {liveState.provider_queue_depth ?? 0}
            </span>
          )}
        </div>
      )}
      {friendlyError(liveState?.error_code, liveState?.error_message) && (
        <div className={styles.error}>{friendlyError(liveState?.error_code, liveState?.error_message)}</div>
      )}

      {/* per-channel cards */}
      {channels.length > 0 && (
        <div className={styles.list}>
          {channels.map((c) => {
            const interim = interimByChannel[c.channel_index];
            const chFinals = finals.filter((s) => s.channel_index === c.channel_index).slice(-3);
            const ratio = liveState?.silence_ratio_by_channel?.[c.channel_index];
            return (
              <div key={c.channel_index} className={styles.chCard}>
                <div className={styles.previewRow}>
                  <span className={styles.rowLabel}>Канал {c.channel_index + 1} — {c.label}
                    {c.side === 'self' ? ' · Мы' : c.side === 'opponent' ? ' · Не мы' : ''}</span>
                  <span className={styles.rowMeta}>
                    {c.track_id.slice(0, 6)} · gen {c.generation}
                    {ratio != null ? ` · тишина ${(ratio * 100).toFixed(0)}%` : ''}
                  </span>
                </div>
                {chFinals.map((s) => <div key={s.segment_id} className={styles.finalText}>{s.transcript}</div>)}
                {interim && <div className={styles.interimText}>{interim.transcript}…</div>}
              </div>
            );
          })}
        </div>
      )}

      {/* chronological */}
      {finals.length > 0 && (
        <details className={styles.details}>
          <summary className={styles.summary}>Общий live candidate ({finals.length})</summary>
          {finals.map((s: MultiChannelLiveSegment) => (
            <div key={s.segment_id} className={styles.chronoRow}>
              <span className={styles.chronoTs}>{fmtTs(s.start_server_ms - startMs)}</span>
              <span className={styles.rowMeta}>
                [{s.side === 'self' ? 'МЫ' : s.side === 'opponent' ? 'НЕ МЫ' : '·'} · К{s.channel_index + 1}]
              </span>
              <span className={styles.chronoText}>{s.transcript}</span>
            </div>
          ))}
        </details>
      )}

      <div className={styles.actions}>
        {active ? (
          <button type="button" className={styles.stopBtn} onClick={onStop}>Остановить</button>
        ) : (
          <button type="button" className={styles.startBtn} disabled={!canStart} onClick={onStart}>
            Запустить live shadow
          </button>
        )}
        {finals.length > 0 && (
          <>
            <button type="button" className={styles.ghost} onClick={onClear}>Очистить candidate</button>
            <button type="button" className={styles.ghost} onClick={copyCandidate}>Копировать</button>
            <button type="button" className={styles.ghost} onClick={downloadJson}>Скачать JSON</button>
          </>
        )}
      </div>
    </div>
  );
}
