import { useState, useMemo, useRef, useEffect } from 'react';
import { downloadBatchResult, getBatchAudioUrl, downloadBatchClip, getBatchResultBlob } from '../../api/batch';
import type { BatchSegment } from '../../api/batch';
import { useBatchJob } from '../../hooks/queries/batch';
import { BatchStatusBadge } from './BatchStatusBadge';
import { theme } from '../../styles/theme';

interface Props {
  jobId: number;
}

type Tab = 'transcript' | 'protocol';

const SPEAKER_PALETTE = ['#5B9CF6', '#2EE59D', '#F5A623', '#FF4B6E', '#B98CFF', '#4DD0E1', '#FF9F6E', '#9CCC65'];

function speakerColor(speaker: string): string {
  const m = speaker.match(/(\d+)/);
  const i = m ? parseInt(m[1], 10) : 0;
  return SPEAKER_PALETTE[i % SPEAKER_PALETTE.length];
}

function mimeExt(mime: string | null): string {
  switch (mime) {
    case 'audio/mpeg': return '.mp3';
    case 'audio/wav': case 'audio/x-wav': return '.wav';
    case 'audio/mp4': case 'audio/x-m4a': case 'audio/m4a': return '.m4a';
    case 'audio/flac': return '.flac';
    case 'audio/webm': return '.webm';
    default: return '.ogg';
  }
}

function fmtTime(sec: number): string {
  const t = Math.max(0, Math.floor(sec));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Подсветка совпадений запроса в тексте реплики. */
function highlight(text: string, q: string): React.ReactNode {
  if (!q) return text;
  const lower = text.toLowerCase();
  const parts: React.ReactNode[] = [];
  let i = 0;
  let idx = lower.indexOf(q, i);
  let k = 0;
  while (idx >= 0) {
    if (idx > i) parts.push(text.slice(i, idx));
    parts.push(
      <mark key={k++} style={{ background: theme.accent.amber, color: theme.bg.primary, borderRadius: 2 }}>
        {text.slice(idx, idx + q.length)}
      </mark>
    );
    i = idx + q.length;
    idx = lower.indexOf(q, i);
  }
  if (i < text.length) parts.push(text.slice(i));
  return parts;
}

export function BatchJobDetail({ jobId }: Props) {
  const { data: job } = useBatchJob(jobId);
  const [tab, setTab] = useState<Tab | null>(null);
  const [query, setQuery] = useState('');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioMime, setAudioMime] = useState<string | null>(null);
  const [curTime, setCurTime] = useState(0);
  const [clipStart, setClipStart] = useState<number | null>(null);
  const [clipEnd, setClipEnd] = useState<number | null>(null);
  const [clipBusy, setClipBusy] = useState(false);
  const [bundleBusy, setBundleBusy] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const segments: BatchSegment[] = job?.segments ?? [];
  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () => (q ? segments.filter((s) => s.text.toLowerCase().includes(q)) : segments),
    [segments, q]
  );

  // индекс активной реплики по позиции воспроизведения (последняя с start <= curTime)
  const activeIdx = useMemo(() => {
    let idx = -1;
    for (let i = 0; i < segments.length; i++) {
      if (segments[i].start <= curTime + 0.15) idx = i;
      else break;
    }
    return idx;
  }, [segments, curTime]);

  // Подгрузить ссылку на аудио, когда задача готова и есть реплики
  useEffect(() => {
    let cancelled = false;
    setAudioUrl(null);
    if (job && job.status === 'done' && (job.segments?.length || job.transcription_text)) {
      getBatchAudioUrl(jobId)
        .then((d) => { if (!cancelled) { setAudioUrl(d.url); setAudioMime(d.content_type); } })
        .catch(() => { /* аудио могло быть удалено — плеер не показываем */ });
    }
    return () => { cancelled = true; };
  }, [jobId, job?.status, job?.segments?.length]);

  // Автопрокрутка активной реплики (только когда не идёт поиск)
  useEffect(() => {
    if (q || activeIdx < 0 || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-seg="${activeIdx}"]`) as HTMLElement | null;
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [activeIdx, q]);

  const seekTo = (start: number) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = start;
    a.play().catch(() => {});
  };

  const downloadFragment = async () => {
    if (clipStart == null || clipEnd == null || clipEnd <= clipStart) return;
    setClipBusy(true);
    try {
      await downloadBatchClip(jobId, clipStart, clipEnd);
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Не удалось вырезать фрагмент');
    } finally {
      setClipBusy(false);
    }
  };

  const downloadAllBundle = async () => {
    if (!job) return;
    const stem = (job.original_filename || 'запись').replace(/\.[^.]+$/, '');
    const parts: Array<{ name: string; getBlob: () => Promise<Blob> }> = [];
    if (job.transcription_text || job.segments?.length) {
      parts.push({ name: `${stem}_транскрипт.txt`, getBlob: async () => (await getBatchResultBlob(jobId, 'transcript_txt')).blob });
      parts.push({ name: `${stem}_транскрипт.json`, getBlob: async () => (await getBatchResultBlob(jobId, 'transcript_json')).blob });
    }
    if (job.protocol_markdown) parts.push({ name: `${stem}_протокол.txt`, getBlob: async () => (await getBatchResultBlob(jobId, 'protocol_txt')).blob });
    if (job.protocol_json) parts.push({ name: `${stem}_протокол.json`, getBlob: async () => (await getBatchResultBlob(jobId, 'protocol_json')).blob });
    if (audioUrl) parts.push({ name: `${stem}_аудио${mimeExt(audioMime)}`, getBlob: async () => await (await fetch(audioUrl)).blob() });
    if (!parts.length) return;

    setBundleBusy(true);
    try {
      const picker = (window as any).showDirectoryPicker;
      if (typeof picker === 'function') {
        let dir;
        try { dir = await picker.call(window, { mode: 'readwrite' }); } catch { setBundleBusy(false); return; }
        for (const p of parts) {
          const blob = await p.getBlob();
          const fh = await dir.getFileHandle(p.name, { create: true });
          const w = await fh.createWritable();
          await w.write(blob);
          await w.close();
        }
      } else {
        for (const p of parts) {
          const blob = await p.getBlob();
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url; a.download = p.name; a.click();
          URL.revokeObjectURL(url);
          await new Promise((r) => setTimeout(r, 300));
        }
      }
    } catch (e: any) {
      alert('Ошибка при скачивании: ' + (e?.message || ''));
    } finally {
      setBundleBusy(false);
    }
  };

  if (!job) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: theme.text.muted, fontSize: 12 }}>
        Загрузка...
      </div>
    );
  }

  const hasTranscript = !!(job.transcription_text || segments.length);
  const activeTab: Tab = tab ?? (job.protocol_markdown && !hasTranscript ? 'protocol' : 'transcript');
  const isProcessing = !['done', 'error'].includes(job.status);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: theme.font.body, fontSize: 13, fontWeight: 600, color: theme.text.primary }}>
          {job.original_filename}
        </span>
        <BatchStatusBadge status={job.status} />
        {(hasTranscript || job.protocol_markdown) && (
          <button onClick={downloadAllBundle} disabled={bundleBusy} style={styles.bundleBtn}>
            {bundleBusy ? 'Скачивание…' : '⬇ Скачать всё'}
          </button>
        )}
      </div>

      {job.error_message && (
        <div style={{ padding: '8px 12px', borderRadius: 6, background: theme.accent.redDim, color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 }}>
          {job.error_message}
        </div>
      )}

      {isProcessing && (
        <div style={{ padding: 16, textAlign: 'center', color: theme.text.secondary, fontFamily: theme.font.body, fontSize: 12 }}>
          Обработка... Статус обновляется автоматически.
        </div>
      )}

      {(hasTranscript || job.protocol_markdown) && (
        <>
          <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${theme.border.default}` }}>
            <TabButton active={activeTab === 'transcript'} onClick={() => setTab('transcript')} disabled={!hasTranscript}>
              Транскрипция
            </TabButton>
            <TabButton active={activeTab === 'protocol'} onClick={() => setTab('protocol')} disabled={!job.protocol_markdown}>
              Протокол
            </TabButton>
          </div>

          {activeTab === 'transcript' && segments.length > 0 && (
            <>
              {audioUrl && (
                <audio
                  ref={audioRef}
                  src={audioUrl}
                  controls
                  preload="none"
                  onTimeUpdate={(e) => setCurTime((e.target as HTMLAudioElement).currentTime)}
                  style={styles.audio}
                />
              )}
              {audioUrl && (
                <div style={styles.trimRow}>
                  <span style={styles.trimLabel}>Фрагмент:</span>
                  <button onClick={() => setClipStart(curTime)} style={styles.trimBtn}>
                    {'⟤'} Начало{clipStart != null ? ` ${fmtTime(clipStart)}` : ''}
                  </button>
                  <button onClick={() => setClipEnd(curTime)} style={styles.trimBtn}>
                    Конец{clipEnd != null ? ` ${fmtTime(clipEnd)}` : ''} {'⟥'}
                  </button>
                  <button
                    onClick={downloadFragment}
                    disabled={clipBusy || clipStart == null || clipEnd == null || (clipEnd ?? 0) <= (clipStart ?? 0)}
                    style={styles.trimDownload}
                  >
                    {clipBusy ? 'Режем…' : '⬇ Скачать фрагмент'}
                  </button>
                  {(clipStart != null || clipEnd != null) && (
                    <button onClick={() => { setClipStart(null); setClipEnd(null); }} style={styles.trimReset}>{'✕'}</button>
                  )}
                </div>
              )}
              <div style={styles.searchRow}>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={audioUrl ? 'Поиск по словам… (клик по реплике — перемотка)' : 'Поиск по словам…'}
                  style={styles.search}
                />
                {q && <span style={styles.count}>{filtered.length} из {segments.length}</span>}
              </div>
              <div ref={listRef} style={styles.segList}>
                {q && filtered.length === 0 && <div style={styles.empty}>Ничего не найдено</div>}
                {segments.map((seg, i) => {
                  if (q && !seg.text.toLowerCase().includes(q)) return null;
                  const isActive = !q && i === activeIdx;
                  return (
                    <div
                      key={i}
                      data-seg={i}
                      onClick={() => seekTo(seg.start)}
                      style={{
                        ...styles.segRow,
                        ...(audioUrl ? styles.segRowClickable : {}),
                        ...(isActive ? styles.segRowActive : {}),
                      }}
                    >
                      <div style={styles.segMeta}>
                        <span style={{ ...styles.speaker, color: speakerColor(seg.speaker) }}>{seg.speaker}</span>
                        <span style={styles.time}>{fmtTime(seg.start)}</span>
                      </div>
                      <div style={styles.segText}>{highlight(seg.text, q)}</div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {activeTab === 'transcript' && segments.length === 0 && job.transcription_text && (
            <div style={styles.flat}>{job.transcription_text}</div>
          )}

          {activeTab === 'protocol' && (
            <div style={styles.flat}>{job.protocol_markdown}</div>
          )}

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {hasTranscript && (
              <>
                <DownloadBtn onClick={() => downloadBatchResult(job.id, 'transcript_txt')} label="TXT" />
                <DownloadBtn onClick={() => downloadBatchResult(job.id, 'transcript_json')} label="JSON" />
              </>
            )}
            {job.protocol_markdown && <DownloadBtn onClick={() => downloadBatchResult(job.id, 'protocol_txt')} label="Протокол TXT" />}
            {job.protocol_json && <DownloadBtn onClick={() => downloadBatchResult(job.id, 'protocol_json')} label="Протокол JSON" />}
            {audioUrl && <a href={audioUrl} style={styles.dlAudio}>{'⬇'} Аудио</a>}
          </div>
        </>
      )}
    </div>
  );
}

function TabButton({ active, onClick, disabled, children }: { active: boolean; onClick: () => void; disabled: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '6px 14px', background: 'transparent', border: 'none',
        borderBottom: active ? `2px solid ${theme.accent.amber}` : '2px solid transparent',
        color: active ? theme.accent.amber : disabled ? theme.text.muted : theme.text.secondary,
        cursor: disabled ? 'default' : 'pointer', fontFamily: theme.font.mono, fontSize: 11,
        fontWeight: 600, letterSpacing: '0.06em', opacity: disabled ? 0.4 : 1,
      }}
    >
      {children}
    </button>
  );
}

function DownloadBtn({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '5px 12px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
        borderRadius: 5, color: theme.accent.amber, cursor: 'pointer', fontFamily: theme.font.mono,
        fontSize: 10, fontWeight: 500, letterSpacing: '0.06em',
      }}
    >
      {'⬇'} {label}
    </button>
  );
}

const styles: Record<string, React.CSSProperties> = {
  audio: {
    width: '100%',
    height: 36,
  },
  bundleBtn: {
    marginLeft: 'auto',
    padding: '5px 12px',
    background: theme.accent.amberGlow,
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 6,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontFamily: theme.font.mono,
    fontSize: 10,
    letterSpacing: '0.06em',
  },
  trimRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
  },
  trimLabel: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
  },
  trimBtn: {
    padding: '5px 10px',
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 5,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontFamily: theme.font.mono,
    fontSize: 10,
    letterSpacing: '0.04em',
  },
  trimDownload: {
    padding: '5px 12px',
    background: 'transparent',
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 5,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontFamily: theme.font.mono,
    fontSize: 10,
    letterSpacing: '0.06em',
  },
  trimReset: {
    padding: '5px 8px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 5,
    color: theme.text.muted,
    cursor: 'pointer',
    fontFamily: theme.font.mono,
    fontSize: 10,
  },
  searchRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  search: {
    flex: 1,
    padding: '7px 12px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
    color: theme.text.primary,
    fontFamily: theme.font.body,
    fontSize: 12,
    outline: 'none',
  },
  count: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
    flexShrink: 0,
  },
  segList: {
    maxHeight: 460,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    padding: '4px 2px',
  },
  segRow: {
    display: 'flex',
    gap: 12,
    alignItems: 'flex-start',
    padding: '4px 8px',
    borderRadius: 6,
    borderLeft: '2px solid transparent',
    transition: 'background 0.15s',
  },
  segRowClickable: {
    cursor: 'pointer',
  },
  segRowActive: {
    background: theme.accent.amberGlow,
    borderLeft: `2px solid ${theme.accent.amber}`,
  },
  dlAudio: {
    padding: '5px 12px',
    background: 'transparent',
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 5,
    color: theme.accent.amber,
    textDecoration: 'none',
    fontFamily: theme.font.mono,
    fontSize: 10,
    fontWeight: 500,
    letterSpacing: '0.06em',
  },
  segMeta: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    flexShrink: 0,
    width: 88,
  },
  speaker: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.02em',
  },
  time: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
  },
  segText: {
    flex: 1,
    fontFamily: theme.font.body,
    fontSize: 13,
    lineHeight: 1.6,
    color: theme.text.primary,
    minWidth: 0,
    wordBreak: 'break-word',
  },
  empty: {
    color: theme.text.muted,
    fontFamily: theme.font.body,
    fontSize: 12,
    textAlign: 'center',
    padding: '16px 0',
  },
  flat: {
    maxHeight: 500,
    overflowY: 'auto',
    padding: '12px 14px',
    borderRadius: 8,
    background: theme.bg.tertiary,
    fontFamily: theme.font.body,
    fontSize: 12,
    lineHeight: 1.7,
    color: theme.text.primary,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
};
