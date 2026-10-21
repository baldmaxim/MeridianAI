import type { FC } from 'react';
import type { PublicSpeakerSide, IngestTrackInfo } from '../../types';
import type { useMultiChannelBatchStt } from '../../hooks/useMultiChannelBatchStt';
import { STAGE_LABELS, friendlyError, fmtTs, trackLabel } from './multiChannelExportUtils';
import styles from './MultiChannelExportModal.module.css';

interface IMultiChannelBatchSectionProps {
  selected: string[];
  byId: Record<string, IngestTrackInfo>;
  sideOverrides: Record<string, PublicSpeakerSide | ''>;
  onSideChange: (id: string, side: PublicSpeakerSide | '') => void;
  privacy: boolean;
  onPrivacyChange: (value: boolean) => void;
  batch: ReturnType<typeof useMultiChannelBatchStt>;
  canRecognize: boolean;
  onRecognize: () => void;
  onRetry: () => void;
  meetingId: number | null;
}

/** Этап 9.5: Batch multi-channel STT — выбор сторон, согласие, прогресс и результат. */
export const MultiChannelBatchSection: FC<IMultiChannelBatchSectionProps> = ({
  selected, byId, sideOverrides, onSideChange, privacy, onPrivacyChange,
  batch, canRecognize, onRecognize, onRetry, meetingId,
}) => {
  const job = batch.job;
  const result = job?.result ?? null;

  const copyCombined = () => {
    if (result?.combined_text) void navigator.clipboard?.writeText(result.combined_text);
  };

  const downloadJson = () => {
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
  };

  return (
    <>
      <div className={styles.divider} />
      <div className={styles.title2}>Batch multi-channel STT</div>
      <div className={styles.note}>
        Аудио выбранных каналов будет отправлено внешнему STT-провайдеру для диагностического
        распознавания. Результат не заменяет основной транскрипт и нигде не сохраняется.
      </div>

      {/* side-селекторы по выбранным каналам */}
      <div className={styles.list}>
        {selected.map((id) => byId[id] && (
          <div key={id} className={styles.row}>
            <span className={styles.rowLabel}>{trackLabel(byId[id])}</span>
            <span className={styles.spacer} />
            {(['self', 'opponent', ''] as const).map((sd) => (
              <button key={sd || 'none'} type="button"
                className={sideOverrides[id] === sd ? styles.sideOn : styles.sideOff}
                onClick={() => onSideChange(id, sd)}>
                {sd === 'self' ? 'Мы' : sd === 'opponent' ? 'Не мы' : 'Не указано'}
              </button>
            ))}
          </div>
        ))}
      </div>

      <label className={styles.privacyRow}>
        <input type="checkbox" checked={privacy} onChange={(e) => onPrivacyChange(e.target.checked)} />
        <span>Я подтверждаю, что имею право отправить эту запись во внешний STT-сервис</span>
      </label>

      {batch.running && job && (
        <div className={styles.preview}>
          <div className={styles.previewHead}>{STAGE_LABELS[job.stage] ?? job.stage}…</div>
          <div className={styles.progressTrack}>
            <div className={styles.progressFill} style={{ transform: `scaleX(${Math.min(1, Math.max(0, job.progress || 0))})` }} />
          </div>
        </div>
      )}

      {job && (job.status === 'failed' || batch.error) && (
        <div className={styles.error}>
          {friendlyError(job.error_code, job.error_message) || batch.error}
        </div>
      )}

      {result && job?.status === 'succeeded' && (
        <div className={styles.preview}>
          <div className={styles.previewHead}>
            {result.provider}/{result.model} · {result.language} ·
            {' '}{(result.duration_ms / 1000).toFixed(1)} с · {result.channels_count} канал(ов)
            {result.provider_request_id ? ` · ${result.provider_request_id}` : ''}
          </div>
          {result.channels.map((c) => (
            <div key={c.channel_index} className={styles.chCard}>
              <div className={styles.previewRow}>
                <span className={styles.rowLabel}>Канал {c.channel_index + 1} — {c.channel_label}
                  {c.side === 'self' ? ' · Мы' : c.side === 'opponent' ? ' · Не мы' : ''}</span>
                <span className={styles.rowMeta}>
                  слов {c.words_count} · сегм. {c.segments_count}
                  {c.average_confidence != null ? ` · ${(c.average_confidence * 100).toFixed(0)}%` : ''}
                </span>
              </div>
              <div className={styles.chText}>{c.transcript || '∅ пусто'}</div>
              {c.warnings.map((w, i) => <div key={i} className={styles.warn}>⚠ {w}</div>)}
            </div>
          ))}
          {result.chronological_segments.length > 0 && (
            <details className={styles.details}>
              <summary className={styles.summary}>Хронологический транскрипт</summary>
              {result.chronological_segments.map((s) => (
                <div key={s.segment_id} className={styles.chronoRow}>
                  <span className={styles.chronoTs}>{fmtTs(s.start)}</span>
                  <span className={styles.rowMeta}>
                    [{s.side === 'self' ? 'МЫ' : s.side === 'opponent' ? 'НЕ МЫ' : '·'} · К{s.channel_index + 1}]
                  </span>
                  <span className={styles.chronoText}>{s.text}</span>
                </div>
              ))}
            </details>
          )}
          {job.comparison && (
            <div className={styles.cmp}>
              <div className={styles.cmpHead}>Сравнение с live transcript</div>
              {job.comparison.available ? (
                <div className={styles.rowMeta}>
                  live {job.comparison.live_words} / batch {job.comparison.batch_words} слов ·
                  {' '}similarity {((job.comparison.text_similarity ?? 0) * 100).toFixed(0)}% ·
                  {' '}WER {((job.comparison.word_error_rate ?? 0) * 100).toFixed(0)}% ·
                  {' '}overlap {(job.comparison.overlap_duration_ms / 1000).toFixed(1)}с
                </div>
              ) : <div className={styles.rowMeta}>Live transcript отсутствует.</div>}
              <div className={styles.dim}>
                Live transcript не является эталонной разметкой. Сравнение только для диагностики.
              </div>
            </div>
          )}
          {result.warnings.map((w, i) => <div key={i} className={styles.warn}>⚠ {w}</div>)}
        </div>
      )}

      <div className={styles.actions}>
        {batch.running && (
          <button type="button" className={styles.ghost} onClick={() => void batch.cancel()}>Отменить</button>
        )}
        {job?.status === 'failed' && job.retryable && (
          <button type="button" className={styles.ghost} onClick={onRetry}>Повторить</button>
        )}
        {result && (
          <>
            <button type="button" className={styles.ghost} onClick={copyCombined}>Копировать текст</button>
            <button type="button" className={styles.ghost} onClick={downloadJson}>Скачать JSON</button>
            <button type="button" className={styles.ghost} onClick={batch.reset}>Сбросить</button>
          </>
        )}
        <span className={styles.spacer} />
        <button type="button" className={styles.primary} disabled={!canRecognize} onClick={onRecognize}>
          {batch.running ? '…' : 'Распознать каналы'}
        </button>
      </div>
    </>
  );
};
