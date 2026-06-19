import { useState } from 'react';
import { downloadBatchResult } from '../../api/batch';
import { useBatchJob } from '../../hooks/queries/batch';
import { BatchStatusBadge } from './BatchStatusBadge';
import { theme } from '../../styles/theme';

interface Props {
  jobId: number;
}

type Tab = 'transcript' | 'protocol';

export function BatchJobDetail({ jobId }: Props) {
  const { data: job } = useBatchJob(jobId); // polling/стоп внутри хука
  const [tab, setTab] = useState<Tab | null>(null); // null = авто-выбор по данным

  if (!job) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: theme.text.muted, fontSize: 12 }}>
        Загрузка...
      </div>
    );
  }

  // авто-протокол, когда он готов, а транскрипта нет; пока пользователь не выберет вручную
  const activeTab: Tab = tab ?? (job.protocol_markdown && !job.transcription_text ? 'protocol' : 'transcript');

  const isProcessing = !['done', 'error'].includes(job.status);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span
          style={{
            fontFamily: theme.font.body,
            fontSize: 13,
            fontWeight: 600,
            color: theme.text.primary,
          }}
        >
          {job.original_filename}
        </span>
        <BatchStatusBadge status={job.status} />
      </div>

      {job.error_message && (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            background: theme.accent.redDim,
            color: theme.accent.red,
            fontFamily: theme.font.mono,
            fontSize: 11,
          }}
        >
          {job.error_message}
        </div>
      )}

      {isProcessing && (
        <div
          style={{
            padding: '16px',
            textAlign: 'center',
            color: theme.text.secondary,
            fontFamily: theme.font.body,
            fontSize: 12,
          }}
        >
          Обработка... Статус обновляется автоматически.
        </div>
      )}

      {/* Tabs */}
      {(job.transcription_text || job.protocol_markdown) && (
        <>
          <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${theme.border.default}`, paddingBottom: 0 }}>
            <TabButton active={activeTab === 'transcript'} onClick={() => setTab('transcript')} disabled={!job.transcription_text}>
              Транскрипция
            </TabButton>
            <TabButton active={activeTab === 'protocol'} onClick={() => setTab('protocol')} disabled={!job.protocol_markdown}>
              Протокол
            </TabButton>
          </div>

          {/* Content */}
          <div
            style={{
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
            }}
          >
            {activeTab === 'transcript' ? job.transcription_text : job.protocol_markdown}
          </div>

          {/* Download buttons */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {job.transcription_text && (
              <>
                <DownloadBtn onClick={() => downloadBatchResult(job.id, 'transcript_txt')} label="TXT" />
                <DownloadBtn onClick={() => downloadBatchResult(job.id, 'transcript_json')} label="JSON" />
              </>
            )}
            {job.protocol_markdown && (
              <DownloadBtn onClick={() => downloadBatchResult(job.id, 'protocol_txt')} label="Протокол TXT" />
            )}
            {job.protocol_json && (
              <DownloadBtn onClick={() => downloadBatchResult(job.id, 'protocol_json')} label="Протокол JSON" />
            )}
          </div>
        </>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '6px 14px',
        background: 'transparent',
        border: 'none',
        borderBottom: active ? `2px solid ${theme.accent.amber}` : '2px solid transparent',
        color: active ? theme.accent.amber : disabled ? theme.text.muted : theme.text.secondary,
        cursor: disabled ? 'default' : 'pointer',
        fontFamily: theme.font.mono,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.06em',
        opacity: disabled ? 0.4 : 1,
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
        padding: '5px 12px',
        background: 'transparent',
        border: `1px solid ${theme.border.amber}`,
        borderRadius: 5,
        color: theme.accent.amber,
        cursor: 'pointer',
        fontFamily: theme.font.mono,
        fontSize: 10,
        fontWeight: 500,
        letterSpacing: '0.06em',
      }}
    >
      {'\u2B07'} {label}
    </button>
  );
}
