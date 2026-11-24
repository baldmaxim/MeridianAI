import { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { downloadBatchResult, getBatchAudioUrl, getBatchResultBlob } from '../../api/batch';
import type { BatchSegment } from '../../api/batch';
import { errorTextFromBlob, fetchBlob, saveBlob } from '../../api/download';
import { createZip } from '../../lib/zip';
import { buildProtocolHtml } from '../../lib/protocolHtml';
import { formatMoscowDateTime } from '../../lib/datetime';
import { useBatchJob } from '../../hooks/queries/batch';
import { useMe } from '../../hooks/queries/auth';
import { BatchStatusBadge } from './BatchStatusBadge';
import { MarkdownView } from '../protocol/MarkdownView';
import { BatchToMeetingModal } from './BatchToMeetingModal';
import { BatchTranscript } from './BatchTranscript';
import { BatchTabButton } from './BatchTabButton';
import { BatchDownloadButton } from './BatchDownloadButton';
import { mimeExt, safeFileName } from './batchDetailUtils';
import { navTo, paths } from '../../lib/navigation';
import styles from './BatchJobDetail.module.css';

interface Props {
  jobId: number;
}

type Tab = 'transcript' | 'protocol';

export function BatchJobDetail({ jobId }: Props) {
  const { data: job } = useBatchJob(jobId);
  const { data: me } = useMe();
  const [tab, setTab] = useState<Tab | null>(null);
  const [toMeetingOpen, setToMeetingOpen] = useState(false);
  const [createdMeetingId, setCreatedMeetingId] = useState<number | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioMime, setAudioMime] = useState<string | null>(null);
  const [bundleBusy, setBundleBusy] = useState(false);
  const [bundleStep, setBundleStep] = useState<string | null>(null);
  // плеер один на обе вкладки: не пересоздаётся при переключении и не теряет позицию
  const audioRef = useRef<HTMLAudioElement>(null);

  const segments: BatchSegment[] = useMemo(() => job?.segments ?? [], [job?.segments]);

  // Подгрузить ссылку на аудио, когда задача готова и есть реплики
  const jobStatus = job?.status;
  const segmentsCount = job?.segments?.length ?? 0;
  const hasText = !!job?.transcription_text;
  useEffect(() => {
    let cancelled = false;
    setAudioUrl(null);
    if (jobStatus === 'done' && (segmentsCount || hasText)) {
      getBatchAudioUrl(jobId)
        .then((d) => { if (!cancelled) { setAudioUrl(d.url); setAudioMime(d.content_type); } })
        .catch(() => { /* аудио могло быть удалено — плеер не показываем */ });
    }
    return () => { cancelled = true; };
  }, [jobId, jobStatus, segmentsCount, hasText]);

  /** Клик по таймкоду протокола: перемотка и пуск, вкладку не переключаем (плеер виден сверху). */
  const seekAudio = useCallback((seconds: number) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = seconds;
    a.play().catch(() => {
      // автовоспроизведение может быть заблокировано браузером — перемотка уже выполнена
    });
  }, []);

  /** Любое скачивание: ошибки показываем, иначе кнопка молча «не работает». */
  const runDownload = async (fn: () => Promise<void>, fallback: string) => {
    try {
      await fn();
    } catch (e) {
      alert(await errorTextFromBlob(e, fallback));
    }
  };

  /** HTML-протокол с просмотрщиком; audioFileName — файл записи рядом (null — без плеера). */
  const makeProtocolHtmlBlob = (audioFileName: string | null): Blob => {
    const html = buildProtocolHtml({
      title: job?.original_filename || 'Запись',
      createdAt: job?.created_at ? formatMoscowDateTime(job.created_at) : undefined,
      protocolMarkdown: job?.protocol_markdown ?? null,
      segments,
      audioFileName,
    });
    return new Blob([html], { type: 'text/html;charset=utf-8' });
  };

  /** Все материалы задачи — одним ZIP: пачку отдельных загрузок браузер блокирует. */
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
    const audioName = safeFileName(`${stem}_аудио${mimeExt(audioMime)}`);
    let audioIncluded = false;
    if (audioUrl) {
      parts.push({
        name: audioName,
        getBlob: async () => {
          const blob = await fetchBlob(audioUrl);
          audioIncluded = true;
          return blob;
        },
      });
    }
    // после аудио: ссылку на запись ставим, только если она реально попала в архив
    if (job.protocol_markdown || segments.length) {
      parts.push({
        name: `${stem}_протокол.html`,
        getBlob: async () => makeProtocolHtmlBlob(audioIncluded ? audioName : null),
      });
    }
    if (!parts.length) return;

    setBundleBusy(true);
    const failed: string[] = [];
    try {
      const entries = [];
      for (let i = 0; i < parts.length; i++) {
        const p = parts[i];
        setBundleStep(`${i + 1}/${parts.length}`);
        // одна недоступная часть (например, аудио) не должна ронять весь архив
        try {
          entries.push({ name: safeFileName(p.name), blob: await p.getBlob() });
        } catch {
          failed.push(p.name);
        }
      }
      if (!entries.length) {
        alert('Не удалось скачать материалы задачи');
        return;
      }
      setBundleStep('архив');
      saveBlob(await createZip(entries), safeFileName(`${stem}_материалы.zip`));
      if (failed.length) alert('В архив не попало: ' + failed.join(', '));
    } catch (e) {
      alert(await errorTextFromBlob(e, 'Ошибка при скачивании'));
    } finally {
      setBundleStep(null);
      setBundleBusy(false);
    }
  };

  if (!job) {
    return (
      <div className={styles.loading}>
        Загрузка...
      </div>
    );
  }

  const fileStem = (job.original_filename || 'запись').replace(/\.[^.]+$/, '');
  const hasTranscript = !!(job.transcription_text || segments.length);
  const activeTab: Tab = tab ?? (job.protocol_markdown && !hasTranscript ? 'protocol' : 'transcript');
  // Встреча из записи: пока запись «батч», у неё есть только markdown-протокол —
  // решения/поручения/риски и кандидаты в базу знаний даёт только финализация встречи.
  const meetingId = job.meeting_id ?? createdMeetingId;
  const isProcessing = !['done', 'error'].includes(job.status);
  // Чужая запись (админ в режиме «Все»): только просмотр, без «Сделать встречу».
  const isForeign = job.owner_id != null && job.owner_id !== me?.id;

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <span className={styles.fileName}>
          {job.original_filename}
        </span>
        <BatchStatusBadge status={job.status} />
        {(hasTranscript || job.protocol_markdown) && (
          <button onClick={downloadAllBundle} disabled={bundleBusy} className={styles.bundleBtn}>
            {bundleBusy ? `Скачивание ${bundleStep ?? ''}…` : '⬇ Скачать всё'}
          </button>
        )}
        {hasTranscript && meetingId == null && !isForeign && (
          <button onClick={() => setToMeetingOpen(true)} className={styles.toMeetingBtn}>
            → Сделать встречу
          </button>
        )}
        {meetingId != null && (
          <button
            type="button"
            className={styles.meetingLink}
            {...navTo(paths.meetingDetail(meetingId))}
          >
            Встреча создана — открыть
          </button>
        )}
      </div>

      <BatchToMeetingModal
        jobId={jobId}
        defaultTitle={job.original_filename}
        open={toMeetingOpen}
        onClose={() => setToMeetingOpen(false)}
        onDone={(r) => setCreatedMeetingId(r.meeting_id)}
      />

      {job.error_message && (
        <div className={styles.errorBox}>
          {job.error_message}
        </div>
      )}

      {isProcessing && (
        <div className={styles.processing}>
          Обработка... Статус обновляется автоматически.
        </div>
      )}

      {(hasTranscript || job.protocol_markdown) && (
        <>
          {/* Плеер + вкладки: вне прокручиваемых областей (скроллятся реплики/протокол), поэтому всегда на виду */}
          <div className={styles.stickyBar}>
            {audioUrl && (
              <audio ref={audioRef} src={audioUrl} controls preload="none" className={styles.audio} />
            )}
            <div className={styles.tabs}>
              <BatchTabButton active={activeTab === 'transcript'} onClick={() => setTab('transcript')} disabled={!hasTranscript}>
                Транскрипция
              </BatchTabButton>
              <BatchTabButton active={activeTab === 'protocol'} onClick={() => setTab('protocol')} disabled={!job.protocol_markdown}>
                Протокол
              </BatchTabButton>
            </div>
          </div>

          {activeTab === 'transcript' && segments.length > 0 && (
            <BatchTranscript jobId={jobId} segments={segments} audioUrl={audioUrl} audioRef={audioRef} />
          )}

          {activeTab === 'transcript' && segments.length === 0 && job.transcription_text && (
            <div className={styles.flat}>{job.transcription_text}</div>
          )}

          {activeTab === 'protocol' && job.protocol_markdown && (
            <div className={styles.protocol}>
              <MarkdownView md={job.protocol_markdown} onTimecode={audioUrl ? seekAudio : undefined} />
            </div>
          )}

          <div className={styles.downloads}>
            {hasTranscript && (
              <>
                <BatchDownloadButton onClick={() => runDownload(() => downloadBatchResult(job.id, 'transcript_txt'), 'Не удалось скачать файл')} label="TXT" />
                <BatchDownloadButton onClick={() => runDownload(() => downloadBatchResult(job.id, 'transcript_json'), 'Не удалось скачать файл')} label="JSON" />
              </>
            )}
            {job.protocol_markdown && <BatchDownloadButton onClick={() => runDownload(() => downloadBatchResult(job.id, 'protocol_txt'), 'Не удалось скачать файл')} label="Протокол TXT" />}
            {job.protocol_markdown && (
              <BatchDownloadButton
                onClick={() => runDownload(async () => saveBlob(makeProtocolHtmlBlob(null), safeFileName(`${fileStem}_протокол.html`)), 'Не удалось собрать HTML')}
                label="Протокол HTML"
              />
            )}
            {job.protocol_json && <BatchDownloadButton onClick={() => runDownload(() => downloadBatchResult(job.id, 'protocol_json'), 'Не удалось скачать файл')} label="Протокол JSON" />}
            {audioUrl && <a href={audioUrl} className={styles.dlAudio}>{'⬇'} Аудио</a>}
          </div>
        </>
      )}
    </div>
  );
}
