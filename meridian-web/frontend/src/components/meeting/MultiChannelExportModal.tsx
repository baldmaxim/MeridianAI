import { useEffect, useMemo, useRef, useState } from 'react';
import { Modal } from '../common/Modal';
import { theme } from '../../styles/theme';
import type { MultiSourceAlignment, IngestTrackInfo, PublicSpeakerSide } from '../../types';
import {
  getMultiChannelExportPlan, downloadMultiChannelWav,
  type MultiChannelExportRequest, type MultiChannelExportPlan, type MultiChannelWindowMode,
} from '../../api/multiChannelExport';
import { useMultiChannelBatchStt } from '../../hooks/useMultiChannelBatchStt';
import type { MultiChannelBatchSttRequest } from '../../api/multiChannelBatchStt';

interface Props {
  open: boolean;
  onClose: () => void;
  meetingId: number | null;
  ingestState: MultiSourceAlignment | null;
}

const MAX_OFFSET = 2000;

function trackLabel(t: IngestTrackInfo): string {
  if (t.role === 'primary') return 'Основной';
  if (t.side_hint === 'self') return 'Shadow · Мы';
  if (t.side_hint === 'opponent') return 'Shadow · Не мы';
  return 'Shadow · сторона ?';
}

function errMessage(e: unknown): string {
  const anyE = e as { response?: { data?: { detail?: { message?: string } | string } } };
  const d = anyE?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && d.message) return d.message;
  return 'Не удалось выполнить экспорт';
}

export function MultiChannelExportModal({ open, onClose, meetingId, ingestState }: Props) {
  const tracks = useMemo(() => ingestState?.tracks ?? [], [ingestState]);
  const [selected, setSelected] = useState<string[]>([]);
  const [windowMode, setWindowMode] = useState<MultiChannelWindowMode>('last');
  const [durationSec, setDurationSec] = useState(30);
  const [startMs, setStartMs] = useState<string>('');
  const [endMs, setEndMs] = useState<string>('');
  const [offsets, setOffsets] = useState<Record<string, number>>({});
  const [showOffsets, setShowOffsets] = useState(false);
  const [showExplicit, setShowExplicit] = useState(false);
  const [plan, setPlan] = useState<MultiChannelExportPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const didInit = useRef(false);

  // Этап 9.5: batch STT
  const batch = useMultiChannelBatchStt({ meetingId });
  const [privacy, setPrivacy] = useState(false);
  const [sideOverrides, setSideOverrides] = useState<Record<string, PublicSpeakerSide | ''>>({});
  const lastBatchReq = useRef<MultiChannelBatchSttRequest | null>(null);

  // дефолтный выбор ТОЛЬКО на открытии. Иначе live-обновления ingestState (~1/с)
  // пересоздают tracks и сбрасывали бы выбор/offsets/plan пользователя.
  useEffect(() => {
    if (!open) { didInit.current = false; return; }
    if (didInit.current) return;
    didInit.current = true;
    setPlan(null); setError(null); setOffsets({});
    setPrivacy(false);          // приватность сбрасывается при каждом открытии, не в localStorage
    batch.reset();
    const withFrames = tracks.filter((t) => t.buffered_frames > 0);
    const primaries = withFrames.filter((t) => t.role === 'primary').map((t) => t.track_id);
    const secondaries = withFrames.filter((t) => t.role === 'secondary')
      .sort((a, b) => (b.last_index ?? 0) - (a.last_index ?? 0));
    const def = [...primaries];
    if (secondaries.length) def.push(secondaries[0].track_id);
    setSelected(def.length ? def : withFrames.slice(0, 1).map((t) => t.track_id));
    // дефолт стороны = track side_hint (primary без стороны не угадываем)
    const ov: Record<string, PublicSpeakerSide | ''> = {};
    for (const t of withFrames) {
      ov[t.track_id] = (t.side_hint === 'self' || t.side_hint === 'opponent') ? t.side_hint : '';
    }
    setSideOverrides(ov);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tracks]);

  const byId = useMemo(() => Object.fromEntries(tracks.map((t) => [t.track_id, t])), [tracks]);

  function toggle(id: string) {
    setPlan(null);
    setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
  }
  function move(id: string, dir: -1 | 1) {
    setPlan(null);
    setSelected((s) => {
      const i = s.indexOf(id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= s.length) return s;
      const next = [...s];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }
  function setOffset(id: string, v: string) {
    setPlan(null);
    const n = Math.trunc(Number(v) || 0);
    const clamped = Math.max(-MAX_OFFSET, Math.min(MAX_OFFSET, n));
    setOffsets((o) => ({ ...o, [id]: clamped }));
  }

  function buildRequest(): MultiChannelExportRequest {
    const channel_offsets_ms: Record<string, number> = {};
    for (const id of selected) if (offsets[id]) channel_offsets_ms[id] = offsets[id];
    const req: MultiChannelExportRequest = {
      track_ids: selected, window_mode: windowMode, channel_offsets_ms,
    };
    if (windowMode === 'last' || windowMode === 'common') req.duration_seconds = durationSec;
    if (windowMode === 'explicit') {
      req.start_server_ms = Number(startMs) || 0;
      req.end_server_ms = Number(endMs) || 0;
    }
    return req;
  }

  async function onCheck() {
    if (meetingId == null || !selected.length) return;
    setBusy(true); setError(null);
    try {
      setPlan(await getMultiChannelExportPlan(meetingId, buildRequest()));
    } catch (e) {
      setPlan(null); setError(errMessage(e));
    } finally { setBusy(false); }
  }

  async function onDownload() {
    if (meetingId == null || !selected.length) return;
    setBusy(true); setError(null);
    try {
      const req = buildRequest();
      const p = await getMultiChannelExportPlan(meetingId, req);  // 1. актуальный plan
      setPlan(p);
      const blob = await downloadMultiChannelWav(meetingId, req); // 2. blob
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `meridian-meeting-${meetingId}-multichannel.wav`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errMessage(e));
    } finally { setBusy(false); }
  }

  function buildBatchRequest(): MultiChannelBatchSttRequest {
    const overrides: Record<string, PublicSpeakerSide | null> = {};
    for (const id of selected) overrides[id] = sideOverrides[id] || null;
    return { export: buildRequest(), channel_side_overrides: overrides, compare_with_live: true };
  }

  function onRecognize() {
    if (meetingId == null || selected.length < 2 || !privacy || batch.running) return;
    const req = buildBatchRequest();
    lastBatchReq.current = req;
    void batch.start(req);
  }

  function onRetry() {
    if (lastBatchReq.current) void batch.start(lastBatchReq.current);
  }

  function handleClose() {
    if (batch.running) void batch.cancel();   // running job отменяется при закрытии
    onClose();
  }

  const job = batch.job;
  const result = job?.result ?? null;
  const canRecognize = meetingId != null && selected.length >= 2 && privacy && !batch.running;

  function copyCombined() {
    if (result?.combined_text) void navigator.clipboard?.writeText(result.combined_text);
  }

  function downloadJson() {
    if (!job) return;
    const payload = { result: job.result, comparison: job.comparison, export_manifest: job.export_manifest };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `meridian-meeting-${meetingId}-multichannel-stt.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <Modal open={open} onClose={handleClose} maxWidth={560}>
      <div style={styles.title}>Тестовый многоканальный WAV</div>
      <div style={styles.note}>
        Каналы выравниваются по общей временной шкале. Пропуски заполняются тишиной
        только в скачиваемом файле.
      </div>
      <div style={styles.privacy}>
        Файл содержит реальную запись речи. Используйте его только с согласия участников.
      </div>

      {/* выбор каналов */}
      <div style={styles.section}>каналы (порядок = порядок в файле)</div>
      <div style={styles.list}>
        {tracks.length === 0 && <div style={styles.dim}>Нет активных источников.</div>}
        {selected.map((id) => {
          const t = byId[id];
          if (!t) return null;
          return (
            <div key={id} style={styles.row}>
              <input type="checkbox" checked readOnly onChange={() => toggle(id)} />
              <span style={styles.rowLabel}>{trackLabel(t)}</span>
              <span style={styles.rowMeta}>
                {(t.buffered_frames * t.frame_ms / 1000).toFixed(1)}с · gaps {t.gaps_count}
              </span>
              <span style={styles.spacer} />
              <button type="button" style={styles.ord} onClick={() => move(id, -1)}>↑</button>
              <button type="button" style={styles.ord} onClick={() => move(id, 1)}>↓</button>
            </div>
          );
        })}
        {tracks.filter((t) => !selected.includes(t.track_id)).map((t) => (
          <div key={t.track_id} style={{ ...styles.row, opacity: 0.65 }}>
            <input type="checkbox" checked={false} onChange={() => toggle(t.track_id)} />
            <span style={styles.rowLabel}>{trackLabel(t)}</span>
            <span style={styles.rowMeta}>
              {(t.buffered_frames * t.frame_ms / 1000).toFixed(1)}с
            </span>
          </div>
        ))}
      </div>

      {/* окно */}
      <div style={styles.section}>окно</div>
      <div style={styles.windowRow}>
        {(['last', 'common', 'explicit'] as MultiChannelWindowMode[]).map((m) => (
          <button key={m} type="button"
            style={windowMode === m ? styles.modeOn : styles.modeOff}
            onClick={() => { setWindowMode(m); setPlan(null); setShowExplicit(m === 'explicit'); }}>
            {m === 'last' ? 'Последние N с' : m === 'common' ? 'Общее окно' : 'Точный интервал'}
          </button>
        ))}
      </div>
      {windowMode !== 'explicit' && (
        <label style={styles.inlineLabel}>
          секунд:
          <input type="number" min={1} value={durationSec} style={styles.num}
            onChange={(e) => { setDurationSec(Math.max(1, Math.trunc(Number(e.target.value) || 1))); setPlan(null); }} />
        </label>
      )}
      {showExplicit && (
        <div style={styles.explicit}>
          <label style={styles.inlineLabel}>start server ms:
            <input type="number" value={startMs} style={styles.num}
              onChange={(e) => { setStartMs(e.target.value); setPlan(null); }} /></label>
          <label style={styles.inlineLabel}>end server ms:
            <input type="number" value={endMs} style={styles.num}
              onChange={(e) => { setEndMs(e.target.value); setPlan(null); }} /></label>
        </div>
      )}

      {/* offsets */}
      <button type="button" style={styles.collapse} onClick={() => setShowOffsets((v) => !v)}>
        {showOffsets ? '▾' : '▸'} Точная подстройка каналов
      </button>
      {showOffsets && (
        <div style={styles.list}>
          <div style={styles.dim}>Положительное значение сдвигает канал позже (мс).</div>
          {selected.map((id) => byId[id] && (
            <label key={id} style={styles.inlineLabel}>
              {trackLabel(byId[id])}:
              <input type="number" value={offsets[id] ?? 0} style={styles.num}
                min={-MAX_OFFSET} max={MAX_OFFSET}
                onChange={(e) => setOffset(id, e.target.value)} />
            </label>
          ))}
        </div>
      )}

      {/* plan preview */}
      {plan && (
        <div style={styles.preview}>
          <div style={styles.previewHead}>
            {plan.channels_count} канал(а/ов) · {(plan.duration_ms / 1000).toFixed(1)} с ·
            {' '}{(plan.wav_bytes / 1048576).toFixed(2)} МБ · {Math.round(plan.sample_rate / 1000)} кГц
          </div>
          {plan.channels.map((c) => (
            <div key={c.channel_index} style={styles.previewRow}>
              <span>Канал {c.channel_index + 1} — {c.label}</span>
              <span style={styles.rowMeta}>
                пропусков {(c.gap_ratio * 100).toFixed(0)}%{c.offset_ms ? ` · сдвиг ${c.offset_ms}мс` : ''}
              </span>
            </div>
          ))}
          {plan.warnings.map((w, i) => (
            <div key={i} style={styles.warn}>⚠ {w}</div>
          ))}
        </div>
      )}

      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.actions}>
        <button type="button" style={styles.ghost} onClick={handleClose}>Закрыть</button>
        <span style={styles.spacer} />
        <button type="button" style={styles.ghost} disabled={busy || !selected.length} onClick={onCheck}>
          {busy ? '…' : 'Проверить'}
        </button>
        <button type="button" style={styles.primary} disabled={busy || !selected.length} onClick={onDownload}>
          {busy ? '…' : 'Скачать WAV'}
        </button>
      </div>

      {/* ── Этап 9.5: Batch multi-channel STT ── */}
      <div style={styles.divider} />
      <div style={styles.title2}>Batch multi-channel STT</div>
      <div style={styles.note}>
        Аудио выбранных каналов будет отправлено внешнему STT-провайдеру для диагностического
        распознавания. Результат не заменяет основной транскрипт и нигде не сохраняется.
      </div>

      {/* side-селекторы по выбранным каналам */}
      <div style={styles.list}>
        {selected.map((id) => byId[id] && (
          <div key={id} style={styles.row}>
            <span style={styles.rowLabel}>{trackLabel(byId[id])}</span>
            <span style={styles.spacer} />
            {(['self', 'opponent', ''] as const).map((sd) => (
              <button key={sd || 'none'} type="button"
                style={sideOverrides[id] === sd ? styles.sideOn : styles.sideOff}
                onClick={() => setSideOverrides((o) => ({ ...o, [id]: sd }))}>
                {sd === 'self' ? 'Мы' : sd === 'opponent' ? 'Не мы' : 'Не указано'}
              </button>
            ))}
          </div>
        ))}
      </div>

      <label style={styles.privacyRow}>
        <input type="checkbox" checked={privacy} onChange={(e) => setPrivacy(e.target.checked)} />
        <span>Я подтверждаю, что имею право отправить эту запись во внешний STT-сервис</span>
      </label>

      {batch.running && job && (
        <div style={styles.preview}>
          <div style={styles.previewHead}>{STAGE_LABELS[job.stage] ?? job.stage}…</div>
          <div style={styles.progressTrack}>
            <div style={{ ...styles.progressFill, width: `${Math.round((job.progress || 0) * 100)}%` }} />
          </div>
        </div>
      )}

      {job && (job.status === 'failed' || batch.error) && (
        <div style={styles.error}>
          {friendlyError(job.error_code, job.error_message) || batch.error}
        </div>
      )}

      {result && job?.status === 'succeeded' && (
        <div style={styles.preview}>
          <div style={styles.previewHead}>
            {result.provider}/{result.model} · {result.language} ·
            {' '}{(result.duration_ms / 1000).toFixed(1)} с · {result.channels_count} канал(ов)
            {result.provider_request_id ? ` · ${result.provider_request_id}` : ''}
          </div>
          {result.channels.map((c) => (
            <div key={c.channel_index} style={styles.chCard}>
              <div style={styles.previewRow}>
                <span style={styles.rowLabel}>Канал {c.channel_index + 1} — {c.channel_label}
                  {c.side === 'self' ? ' · Мы' : c.side === 'opponent' ? ' · Не мы' : ''}</span>
                <span style={styles.rowMeta}>
                  слов {c.words_count} · сегм. {c.segments_count}
                  {c.average_confidence != null ? ` · ${(c.average_confidence * 100).toFixed(0)}%` : ''}
                </span>
              </div>
              <div style={styles.chText}>{c.transcript || '∅ пусто'}</div>
              {c.warnings.map((w, i) => <div key={i} style={styles.warn}>⚠ {w}</div>)}
            </div>
          ))}
          {result.chronological_segments.length > 0 && (
            <details style={styles.details}>
              <summary style={styles.summary}>Хронологический транскрипт</summary>
              {result.chronological_segments.map((s) => (
                <div key={s.segment_id} style={styles.chronoRow}>
                  <span style={styles.chronoTs}>{fmtTs(s.start)}</span>
                  <span style={styles.rowMeta}>
                    [{s.side === 'self' ? 'МЫ' : s.side === 'opponent' ? 'НЕ МЫ' : '·'} · К{s.channel_index + 1}]
                  </span>
                  <span style={styles.chronoText}>{s.text}</span>
                </div>
              ))}
            </details>
          )}
          {job.comparison && (
            <div style={styles.cmp}>
              <div style={styles.cmpHead}>Сравнение с live transcript</div>
              {job.comparison.available ? (
                <div style={styles.rowMeta}>
                  live {job.comparison.live_words} / batch {job.comparison.batch_words} слов ·
                  {' '}similarity {((job.comparison.text_similarity ?? 0) * 100).toFixed(0)}% ·
                  {' '}WER {((job.comparison.word_error_rate ?? 0) * 100).toFixed(0)}% ·
                  {' '}overlap {(job.comparison.overlap_duration_ms / 1000).toFixed(1)}с
                </div>
              ) : <div style={styles.rowMeta}>Live transcript отсутствует.</div>}
              <div style={styles.dim}>
                Live transcript не является эталонной разметкой. Сравнение только для диагностики.
              </div>
            </div>
          )}
          {result.warnings.map((w, i) => <div key={i} style={styles.warn}>⚠ {w}</div>)}
        </div>
      )}

      <div style={styles.actions}>
        {batch.running && (
          <button type="button" style={styles.ghost} onClick={() => void batch.cancel()}>Отменить</button>
        )}
        {job?.status === 'failed' && job.retryable && (
          <button type="button" style={styles.ghost} onClick={onRetry}>Повторить</button>
        )}
        {result && (
          <>
            <button type="button" style={styles.ghost} onClick={copyCombined}>Копировать текст</button>
            <button type="button" style={styles.ghost} onClick={downloadJson}>Скачать JSON</button>
            <button type="button" style={styles.ghost} onClick={batch.reset}>Сбросить</button>
          </>
        )}
        <span style={styles.spacer} />
        <button type="button" style={styles.primary} disabled={!canRecognize} onClick={onRecognize}>
          {batch.running ? '…' : 'Распознать каналы'}
        </button>
      </div>
    </Modal>
  );
}

const STAGE_LABELS: Record<string, string> = {
  queued: 'В очереди',
  preparing: 'Подготовка и сборка WAV',
  transcribing: 'Отправка в STT',
  parsing: 'Обработка ответа',
  comparing: 'Сравнение',
  succeeded: 'Готово',
};

function friendlyError(code: string | null, message: string | null): string | null {
  if (!code) return null;
  if (code === 'PROVIDER_AUTH' || code === 'PROVIDER_NOT_CONFIGURED') return 'STT-провайдер не настроен';
  if (code === 'PROVIDER_TIMEOUT') return 'Провайдер не успел обработать запись';
  if (code === 'PROVIDER_RATE_LIMIT') return 'Лимит STT-провайдера исчерпан. Повторите позже';
  return message || 'Ошибка распознавания каналов';
}

function fmtTs(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = (sec - m * 60);
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

const styles: Record<string, React.CSSProperties> = {
  title: { fontFamily: theme.font.heading, fontSize: 18, fontWeight: 800, color: theme.text.primary },
  note: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, lineHeight: 1.5 },
  privacy: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.amber, lineHeight: 1.5 },
  section: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, letterSpacing: '0.08em', marginTop: 4 },
  list: { display: 'flex', flexDirection: 'column', gap: 6 },
  row: { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', background: theme.bg.input, borderRadius: 8 },
  rowLabel: { fontFamily: theme.font.body, fontSize: 13, color: theme.text.primary },
  rowMeta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  spacer: { flex: 1 },
  ord: { padding: '2px 8px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.secondary, cursor: 'pointer' },
  dim: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  windowRow: { display: 'flex', gap: 6, flexWrap: 'wrap' as const },
  modeOff: { padding: '6px 12px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 8, color: theme.text.secondary, cursor: 'pointer', fontSize: 12 },
  modeOn: { padding: '6px 12px', background: 'rgba(245,166,35,0.14)', border: `1px solid ${theme.accent.amber}`, borderRadius: 8, color: theme.accent.amber, cursor: 'pointer', fontSize: 12, fontWeight: 600 },
  inlineLabel: { display: 'flex', alignItems: 'center', gap: 8, fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary },
  num: { width: 110, padding: '4px 8px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.primary, fontFamily: theme.font.mono },
  explicit: { display: 'flex', flexDirection: 'column', gap: 6 },
  collapse: { alignSelf: 'flex-start', background: 'transparent', border: 'none', color: theme.text.secondary, cursor: 'pointer', fontFamily: theme.font.mono, fontSize: 12, padding: 0 },
  preview: { display: 'flex', flexDirection: 'column', gap: 4, padding: 10, background: theme.bg.input, borderRadius: 10 },
  previewHead: { fontFamily: theme.font.mono, fontSize: 12, fontWeight: 600, color: theme.accent.green },
  previewRow: { display: 'flex', justifyContent: 'space-between', gap: 8, fontFamily: theme.font.body, fontSize: 12, color: theme.text.primary },
  warn: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.amber },
  error: { fontFamily: theme.font.mono, fontSize: 12, color: theme.accent.red },
  actions: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, flexWrap: 'wrap' as const },
  ghost: { padding: '8px 14px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 8, color: theme.text.secondary, cursor: 'pointer', fontSize: 13 },
  primary: { padding: '8px 16px', background: theme.accent.amber, border: 'none', borderRadius: 8, color: '#080A0F', cursor: 'pointer', fontSize: 13, fontWeight: 600 },
  divider: { height: 1, background: theme.border.default, margin: '6px 0' },
  title2: { fontFamily: theme.font.heading, fontSize: 15, fontWeight: 800, color: theme.text.primary },
  sideOff: { padding: '4px 10px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6, color: theme.text.secondary, cursor: 'pointer', fontSize: 11 },
  sideOn: { padding: '4px 10px', background: 'rgba(245,166,35,0.14)', border: `1px solid ${theme.accent.amber}`, borderRadius: 6, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontWeight: 600 },
  privacyRow: { display: 'flex', alignItems: 'flex-start', gap: 8, fontFamily: theme.font.body, fontSize: 12, color: theme.text.secondary, lineHeight: 1.4 },
  progressTrack: { height: 6, borderRadius: 3, background: theme.bg.input, overflow: 'hidden', marginTop: 6 },
  progressFill: { height: '100%', background: theme.accent.amber, borderRadius: 3, transition: 'width 0.3s ease' },
  chCard: { display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px', background: theme.bg.card, borderRadius: 8 },
  chText: { fontFamily: theme.font.body, fontSize: 12, color: theme.text.primary, lineHeight: 1.4, whiteSpace: 'pre-wrap' as const },
  details: { background: theme.bg.input, borderRadius: 8, padding: '6px 8px' },
  summary: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, cursor: 'pointer' },
  chronoRow: { display: 'flex', gap: 8, alignItems: 'baseline', padding: '2px 0' },
  chronoTs: { fontFamily: theme.font.mono, fontSize: 10, color: theme.accent.green },
  chronoText: { fontFamily: theme.font.body, fontSize: 12, color: theme.text.primary },
  cmp: { display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 8px', background: theme.bg.card, borderRadius: 8 },
  cmpHead: { fontFamily: theme.font.mono, fontSize: 11, fontWeight: 600, color: theme.text.secondary },
};
