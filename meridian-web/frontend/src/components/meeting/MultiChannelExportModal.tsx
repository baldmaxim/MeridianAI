import { useEffect, useMemo, useRef, useState } from 'react';
import { Modal } from '../common/Modal';
import { Collapse, TextInput } from '../common';
import type { MultiSourceAlignment, PublicSpeakerSide } from '../../types';
import {
  getMultiChannelExportPlan, downloadMultiChannelWav,
  type MultiChannelExportRequest, type MultiChannelExportPlan, type MultiChannelWindowMode,
} from '../../api/multiChannelExport';
import { useMultiChannelBatchStt } from '../../hooks/useMultiChannelBatchStt';
import type { MultiChannelBatchSttRequest } from '../../api/multiChannelBatchStt';
import { MultiChannelBatchSection } from './MultiChannelBatchSection';
import { errMessage, trackLabel } from './multiChannelExportUtils';
import styles from './MultiChannelExportModal.module.css';

interface Props {
  open: boolean;
  onClose: () => void;
  meetingId: number | null;
  ingestState: MultiSourceAlignment | null;
}

const MAX_OFFSET = 2000;

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

  const canRecognize = meetingId != null && selected.length >= 2 && privacy && !batch.running;

  return (
    <Modal open={open} onClose={handleClose} maxWidth={560}>
      <div className={styles.title}>Тестовый многоканальный WAV</div>
      <div className={styles.note}>
        Каналы выравниваются по общей временной шкале. Пропуски заполняются тишиной
        только в скачиваемом файле.
      </div>
      <div className={styles.privacy}>
        Файл содержит реальную запись речи. Используйте его только с согласия участников.
      </div>

      {/* выбор каналов */}
      <div className={styles.section}>каналы (порядок = порядок в файле)</div>
      <div className={styles.list}>
        {tracks.length === 0 && <div className={styles.dim}>Нет активных источников.</div>}
        {selected.map((id) => {
          const t = byId[id];
          if (!t) return null;
          return (
            <div key={id} className={styles.row}>
              <input type="checkbox" checked readOnly onChange={() => toggle(id)} />
              <span className={styles.rowLabel}>{trackLabel(t)}</span>
              <span className={styles.rowMeta}>
                {(t.buffered_frames * t.frame_ms / 1000).toFixed(1)}с · gaps {t.gaps_count}
              </span>
              <span className={styles.spacer} />
              <button type="button" className={styles.ord} onClick={() => move(id, -1)}>↑</button>
              <button type="button" className={styles.ord} onClick={() => move(id, 1)}>↓</button>
            </div>
          );
        })}
        {tracks.filter((t) => !selected.includes(t.track_id)).map((t) => (
          <div key={t.track_id} className={`${styles.row} ${styles.rowDim}`}>
            <input type="checkbox" checked={false} onChange={() => toggle(t.track_id)} />
            <span className={styles.rowLabel}>{trackLabel(t)}</span>
            <span className={styles.rowMeta}>
              {(t.buffered_frames * t.frame_ms / 1000).toFixed(1)}с
            </span>
          </div>
        ))}
      </div>

      {/* окно */}
      <div className={styles.section}>окно</div>
      <div className={styles.windowRow}>
        {(['last', 'common', 'explicit'] as MultiChannelWindowMode[]).map((m) => (
          <button key={m} type="button"
            className={windowMode === m ? styles.modeOn : styles.modeOff}
            onClick={() => { setWindowMode(m); setPlan(null); setShowExplicit(m === 'explicit'); }}>
            {m === 'last' ? 'Последние N с' : m === 'common' ? 'Общее окно' : 'Точный интервал'}
          </button>
        ))}
      </div>
      {windowMode !== 'explicit' && (
        <label className={styles.inlineLabel}>
          секунд:
          <TextInput type="number" min={1} value={durationSec} className={styles.numWrap} inputClassName={styles.num}
            clearLabel="число секунд"
            onClear={() => { setDurationSec(1); setPlan(null); }}
            onChange={(e) => { setDurationSec(Math.max(1, Math.trunc(Number(e.target.value) || 1))); setPlan(null); }} />
        </label>
      )}
      <Collapse open={showExplicit}>
        <div className={styles.explicit}>
          <label className={styles.inlineLabel}>start server ms:
            <TextInput type="number" value={startMs} className={styles.numWrap} inputClassName={styles.num}
              clearLabel="начало интервала"
              onClear={() => { setStartMs(''); setPlan(null); }}
              onChange={(e) => { setStartMs(e.target.value); setPlan(null); }} /></label>
          <label className={styles.inlineLabel}>end server ms:
            <TextInput type="number" value={endMs} className={styles.numWrap} inputClassName={styles.num}
              clearLabel="конец интервала"
              onClear={() => { setEndMs(''); setPlan(null); }}
              onChange={(e) => { setEndMs(e.target.value); setPlan(null); }} /></label>
        </div>
      </Collapse>

      {/* offsets */}
      <button type="button" className={styles.collapse} onClick={() => setShowOffsets((v) => !v)}>
        {showOffsets ? '▾' : '▸'} Точная подстройка каналов
      </button>
      <Collapse open={showOffsets}>
        <div className={styles.list}>
          <div className={styles.dim}>Положительное значение сдвигает канал позже (мс).</div>
          {selected.map((id) => byId[id] && (
            <label key={id} className={styles.inlineLabel}>
              {trackLabel(byId[id])}:
              <TextInput type="number" value={offsets[id] ?? 0} className={styles.numWrap} inputClassName={styles.num}
                min={-MAX_OFFSET} max={MAX_OFFSET}
                clearLabel="сдвиг канала"
                onClear={() => setOffset(id, '0')}
                onChange={(e) => setOffset(id, e.target.value)} />
            </label>
          ))}
        </div>
      </Collapse>

      {/* plan preview */}
      {plan && (
        <div className={styles.preview}>
          <div className={styles.previewHead}>
            {plan.channels_count} канал(а/ов) · {(plan.duration_ms / 1000).toFixed(1)} с ·
            {' '}{(plan.wav_bytes / 1048576).toFixed(2)} МБ · {Math.round(plan.sample_rate / 1000)} кГц
          </div>
          {plan.channels.map((c) => (
            <div key={c.channel_index} className={styles.previewRow}>
              <span>Канал {c.channel_index + 1} — {c.label}</span>
              <span className={styles.rowMeta}>
                пропусков {(c.gap_ratio * 100).toFixed(0)}%{c.offset_ms ? ` · сдвиг ${c.offset_ms}мс` : ''}
              </span>
            </div>
          ))}
          {plan.warnings.map((w, i) => (
            <div key={i} className={styles.warn}>⚠ {w}</div>
          ))}
        </div>
      )}

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} onClick={handleClose}>Закрыть</button>
        <span className={styles.spacer} />
        <button type="button" className={styles.ghost} disabled={busy || !selected.length} onClick={onCheck}>
          {busy ? '…' : 'Проверить'}
        </button>
        <button type="button" className={styles.primary} disabled={busy || !selected.length} onClick={onDownload}>
          {busy ? '…' : 'Скачать WAV'}
        </button>
      </div>
      <MultiChannelBatchSection
        selected={selected}
        byId={byId}
        sideOverrides={sideOverrides}
        onSideChange={(id, sd) => setSideOverrides((o) => ({ ...o, [id]: sd }))}
        privacy={privacy}
        onPrivacyChange={setPrivacy}
        batch={batch}
        canRecognize={canRecognize}
        onRecognize={onRecognize}
        onRetry={onRetry}
        meetingId={meetingId}
      />
    </Modal>
  );
}
