import { useEffect, useMemo, useRef, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
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
    <div style={styles.panel}>
      <div style={styles.note}>
        Выбранные каналы объединяются в многоканальный поток и отправляются внешнему STT-провайдеру.
      </div>
      <div style={styles.important}>
        Основной transcript и AI-подсказки продолжают использовать текущий STT. Результат ниже —
        только диагностический candidate.
      </div>
      <div style={styles.privacy}>
        Аудио всех выбранных каналов будет передаваться внешнему STT-сервису.
      </div>

      {/* выбор каналов */}
      <div style={styles.section}>каналы (порядок = порядок в потоке)</div>
      <div style={styles.list}>
        {tracks.length === 0 && <div style={styles.dim}>Нет активных источников.</div>}
        {selected.map((id) => byId[id] && (
          <div key={id} style={styles.row}>
            <input type="checkbox" checked readOnly disabled={active} onChange={() => toggle(id)} />
            <span style={styles.rowLabel}>{trackLabel(byId[id])}</span>
            <span style={styles.rowMeta}>
              {(byId[id].buffered_frames * byId[id].frame_ms / 1000).toFixed(1)}с · gaps {byId[id].gaps_count}
            </span>
            <span style={styles.spacer} />
            {(['self', 'opponent', ''] as const).map((sd) => (
              <button key={sd || 'none'} type="button" disabled={active}
                style={sideOverrides[id] === sd ? styles.sideOn : styles.sideOff}
                onClick={() => setSideOverrides((o) => ({ ...o, [id]: sd }))}>
                {sd === 'self' ? 'Мы' : sd === 'opponent' ? 'Не мы' : '?'}
              </button>
            ))}
            <button type="button" style={styles.ord} disabled={active} onClick={() => move(id, -1)}>↑</button>
            <button type="button" style={styles.ord} disabled={active} onClick={() => move(id, 1)}>↓</button>
          </div>
        ))}
        {!active && tracks.filter((t) => !selected.includes(t.track_id)).map((t) => (
          <div key={t.track_id} style={{ ...styles.row, opacity: 0.6 }}>
            <input type="checkbox" checked={false} onChange={() => toggle(t.track_id)} />
            <span style={styles.rowLabel}>{trackLabel(t)}</span>
            <span style={styles.rowMeta}>{(t.buffered_frames * t.frame_ms / 1000).toFixed(1)}с</span>
          </div>
        ))}
      </div>

      {!alignmentReady && <div style={styles.warn}>Каналы ещё не выровнены — старт недоступен.</div>}

      <label style={styles.privacyRow}>
        <input type="checkbox" checked={consent} disabled={active}
          onChange={(e) => setConsent(e.target.checked)} />
        <span>Я подтверждаю, что имею право передавать эту запись внешнему STT-сервису</span>
      </label>

      {/* статус */}
      {liveState && status !== 'idle' && (
        <div style={styles.statusRow}>
          <span style={{ ...styles.badge, color: status === 'failed' ? theme.accent.red
            : status === 'streaming' ? theme.accent.green : theme.accent.amber }}>
            {STATUS_LABEL[status] ?? status}
          </span>
          {liveState.provider && <span style={styles.rowMeta}>{liveState.provider}/{liveState.model}</span>}
          {status === 'streaming' && (
            <span style={styles.rowMeta}>
              чанков {liveState.chunks_sent ?? 0} · кадров {liveState.frames_sent ?? 0} ·
              {' '}{((liveState.bytes_sent ?? 0) / 1024).toFixed(0)} КБ · очередь {liveState.provider_queue_depth ?? 0}
            </span>
          )}
        </div>
      )}
      {friendlyError(liveState?.error_code, liveState?.error_message) && (
        <div style={styles.error}>{friendlyError(liveState?.error_code, liveState?.error_message)}</div>
      )}

      {/* per-channel cards */}
      {channels.length > 0 && (
        <div style={styles.list}>
          {channels.map((c) => {
            const interim = interimByChannel[c.channel_index];
            const chFinals = finals.filter((s) => s.channel_index === c.channel_index).slice(-3);
            const ratio = liveState?.silence_ratio_by_channel?.[c.channel_index];
            return (
              <div key={c.channel_index} style={styles.chCard}>
                <div style={styles.previewRow}>
                  <span style={styles.rowLabel}>Канал {c.channel_index + 1} — {c.label}
                    {c.side === 'self' ? ' · Мы' : c.side === 'opponent' ? ' · Не мы' : ''}</span>
                  <span style={styles.rowMeta}>
                    {c.track_id.slice(0, 6)} · gen {c.generation}
                    {ratio != null ? ` · тишина ${(ratio * 100).toFixed(0)}%` : ''}
                  </span>
                </div>
                {chFinals.map((s) => <div key={s.segment_id} style={styles.finalText}>{s.transcript}</div>)}
                {interim && <div style={styles.interimText}>{interim.transcript}…</div>}
              </div>
            );
          })}
        </div>
      )}

      {/* chronological */}
      {finals.length > 0 && (
        <details style={styles.details}>
          <summary style={styles.summary}>Общий live candidate ({finals.length})</summary>
          {finals.map((s: MultiChannelLiveSegment) => (
            <div key={s.segment_id} style={styles.chronoRow}>
              <span style={styles.chronoTs}>{fmtTs(s.start_server_ms - startMs)}</span>
              <span style={styles.rowMeta}>
                [{s.side === 'self' ? 'МЫ' : s.side === 'opponent' ? 'НЕ МЫ' : '·'} · К{s.channel_index + 1}]
              </span>
              <span style={styles.chronoText}>{s.transcript}</span>
            </div>
          ))}
        </details>
      )}

      <div style={styles.actions}>
        {active ? (
          <button type="button" style={styles.stopBtn} onClick={onStop}>Остановить</button>
        ) : (
          <button type="button" style={styles.startBtn} disabled={!canStart} onClick={onStart}>
            Запустить live shadow
          </button>
        )}
        {finals.length > 0 && (
          <>
            <button type="button" style={styles.ghost} onClick={onClear}>Очистить candidate</button>
            <button type="button" style={styles.ghost} onClick={copyCandidate}>Копировать</button>
            <button type="button" style={styles.ghost} onClick={downloadJson}>Скачать JSON</button>
          </>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  panel: { display: 'flex', flexDirection: 'column', gap: 10 },
  note: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, lineHeight: 1.5 },
  important: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.green, lineHeight: 1.5 },
  privacy: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.amber, lineHeight: 1.5 },
  section: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, letterSpacing: '0.08em', marginTop: 4 },
  list: { display: 'flex', flexDirection: 'column', gap: 6 },
  row: { display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', background: theme.bg.input, borderRadius: 8, flexWrap: 'wrap' as const },
  rowLabel: { fontFamily: theme.font.body, fontSize: 13, color: theme.text.primary },
  rowMeta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  spacer: { flex: 1 },
  ord: { padding: '2px 8px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.secondary, cursor: 'pointer' },
  sideOff: { padding: '3px 8px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.secondary, cursor: 'pointer', fontSize: 11 },
  sideOn: { padding: '3px 8px', background: 'rgba(245,166,35,0.14)', border: `1px solid ${theme.accent.amber}`, borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontWeight: 600 },
  dim: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  warn: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.amber },
  privacyRow: { display: 'flex', alignItems: 'flex-start', gap: 8, fontFamily: theme.font.body, fontSize: 12, color: theme.text.secondary, lineHeight: 1.4 },
  statusRow: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' as const },
  badge: { fontFamily: theme.font.mono, fontSize: 12, fontWeight: 600 },
  error: { fontFamily: theme.font.mono, fontSize: 12, color: theme.accent.red },
  chCard: { display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px', background: theme.bg.card, borderRadius: 8 },
  previewRow: { display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' },
  finalText: { fontFamily: theme.font.body, fontSize: 12, color: theme.text.primary, lineHeight: 1.4 },
  interimText: { fontFamily: theme.font.body, fontSize: 12, color: theme.text.muted, fontStyle: 'italic', lineHeight: 1.4 },
  details: { background: theme.bg.input, borderRadius: 8, padding: '6px 8px' },
  summary: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, cursor: 'pointer' },
  chronoRow: { display: 'flex', gap: 8, alignItems: 'baseline', padding: '2px 0' },
  chronoTs: { fontFamily: theme.font.mono, fontSize: 10, color: theme.accent.green },
  chronoText: { fontFamily: theme.font.body, fontSize: 12, color: theme.text.primary },
  actions: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, flexWrap: 'wrap' as const },
  startBtn: { padding: '8px 16px', background: theme.accent.amber, border: 'none', borderRadius: 8, color: '#080A0F', cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  stopBtn: { padding: '8px 16px', background: 'transparent', border: `1px solid ${theme.accent.red}`, borderRadius: 8, color: theme.accent.red, cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  ghost: { padding: '8px 14px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 8, color: theme.text.secondary, cursor: 'pointer', fontSize: 13 },
};
