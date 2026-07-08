import { useState, useMemo } from 'react';
import { downloadBatchResult } from '../../api/batch';
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

  const segments: BatchSegment[] = job?.segments ?? [];
  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () => (q ? segments.filter((s) => s.text.toLowerCase().includes(q)) : segments),
    [segments, q]
  );

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
              <div style={styles.searchRow}>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Поиск по словам…"
                  style={styles.search}
                />
                {q && <span style={styles.count}>{filtered.length} из {segments.length}</span>}
              </div>
              <div style={styles.segList}>
                {filtered.length === 0 && <div style={styles.empty}>Ничего не найдено</div>}
                {filtered.map((seg, i) => (
                  <div key={i} style={styles.segRow}>
                    <div style={styles.segMeta}>
                      <span style={{ ...styles.speaker, color: speakerColor(seg.speaker) }}>{seg.speaker}</span>
                      <span style={styles.time}>{fmtTime(seg.start)}</span>
                    </div>
                    <div style={styles.segText}>{highlight(seg.text, q)}</div>
                  </div>
                ))}
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
