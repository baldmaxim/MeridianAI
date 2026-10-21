import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import type { FC } from 'react';
import { downloadBatchClip } from '../../api/batch';
import type { BatchSegment } from '../../api/batch';
import { errorTextFromBlob } from '../../api/download';
import { TextInput } from '../common';
import { HighlightText } from './HighlightText';
import { fmtTime } from './batchDetailUtils';
import styles from './BatchTranscript.module.css';
import { cx } from '../../utils/cx';

interface IBatchTranscriptProps {
  jobId: number;
  segments: BatchSegment[];
  audioUrl: string | null;
}

/** Цвета спикеров — токены темы (классы speakerTone0..7 в BatchTranscript.module.css). */
const SPEAKER_TONES = [
  styles.speakerTone0, styles.speakerTone1, styles.speakerTone2, styles.speakerTone3,
  styles.speakerTone4, styles.speakerTone5, styles.speakerTone6, styles.speakerTone7,
];

function speakerTone(speaker: string): string {
  const m = speaker.match(/(\d+)/);
  const i = m ? parseInt(m[1], 10) : 0;
  return SPEAKER_TONES[i % SPEAKER_TONES.length];
}

/** Реплики с поиском, плеером и нарезкой фрагмента. */
export const BatchTranscript: FC<IBatchTranscriptProps> = ({ jobId, segments, audioUrl }) => {
  const [query, setQuery] = useState('');
  const [activeIdx, setActiveIdx] = useState(-1);
  const [clipStart, setClipStart] = useState<number | null>(null);
  const [clipEnd, setClipEnd] = useState<number | null>(null);
  const [clipBusy, setClipBusy] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () => (q ? segments.filter((s) => s.text.toLowerCase().includes(q)) : segments),
    [segments, q]
  );

  // Активную реплику обновляем ТОЛЬКО при её смене (не на каждый timeupdate ~4×/сек) —
  // иначе список из сотен реплик перерисовывается постоянно и залипают пауза/пуск.
  const handleTimeUpdate = useCallback((e: React.SyntheticEvent<HTMLAudioElement>) => {
    const t = e.currentTarget.currentTime;
    let idx = -1;
    for (let i = 0; i < segments.length; i++) {
      if (segments[i].start <= t + 0.15) idx = i;
      else break;
    }
    setActiveIdx((prev) => (prev === idx ? prev : idx));
  }, [segments]);

  // Автопрокрутка активной реплики (только когда не идёт поиск)
  useEffect(() => {
    if (q || activeIdx < 0 || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-seg="${activeIdx}"]`) as HTMLElement | null;
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [activeIdx, q]);

  const seekTo = useCallback((start: number) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = start;
    a.play().catch(() => {
      // автовоспроизведение может быть заблокировано браузером — перемотка уже выполнена
    });
  }, []);

  const downloadFragment = async () => {
    if (clipStart == null || clipEnd == null || clipEnd <= clipStart) return;
    setClipBusy(true);
    try {
      await downloadBatchClip(jobId, clipStart, clipEnd);
    } catch (e) {
      alert(await errorTextFromBlob(e, 'Не удалось вырезать фрагмент'));
    } finally {
      setClipBusy(false);
    }
  };

  // Мемоизированный список реплик: перерисовывается только при смене активной реплики/поиска,
  // а не на каждый tick воспроизведения и не при кликах по кнопкам нарезки/скачивания.
  const renderedSegments = useMemo(
    () =>
      segments.map((seg, i) => {
        // Поиск идёт и по переводу: искать турецкую реплику по-русски — нормальное желание
        if (q && !seg.text.toLowerCase().includes(q) && !seg.text_ru?.toLowerCase().includes(q))
          return null;
        const isActive = !q && i === activeIdx;
        return (
          <div
            key={i}
            data-seg={i}
            onClick={() => seekTo(seg.start)}
            className={cx(styles.segRow, audioUrl && styles.segRowClickable, isActive && styles.segRowActive)}
          >
            <div className={styles.segMeta}>
              <span className={cx(styles.speaker, speakerTone(seg.speaker))}>{seg.speaker}</span>
              <span className={styles.time}>{fmtTime(seg.start)}</span>
            </div>
            <div className={styles.segBody}>
              <div className={styles.segText}><HighlightText text={seg.text} query={q} /></div>
              {seg.text_ru && (
                <div className={styles.segTextRu}>
                  <span className={styles.ruTag}>RU</span>
                  <span><HighlightText text={seg.text_ru} query={q} /></span>
                </div>
              )}
            </div>
          </div>
        );
      }),
    [segments, q, activeIdx, audioUrl, seekTo]
  );

  return (
    <>
      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl}
          controls
          preload="none"
          onTimeUpdate={handleTimeUpdate}
          className={styles.audio}
        />
      )}
      {audioUrl && (
        <div className={styles.trimRow}>
          <span className={styles.trimLabel}>Фрагмент:</span>
          <button onClick={() => setClipStart(audioRef.current?.currentTime ?? 0)} className={styles.trimBtn}>
            {'⟤'} Начало{clipStart != null ? ` ${fmtTime(clipStart)}` : ''}
          </button>
          <button onClick={() => setClipEnd(audioRef.current?.currentTime ?? 0)} className={styles.trimBtn}>
            Конец{clipEnd != null ? ` ${fmtTime(clipEnd)}` : ''} {'⟥'}
          </button>
          <button
            onClick={downloadFragment}
            disabled={clipBusy || clipStart == null || clipEnd == null || (clipEnd ?? 0) <= (clipStart ?? 0)}
            className={styles.trimDownload}
          >
            {clipBusy ? 'Режем…' : '⬇ Скачать фрагмент'}
          </button>
          {(clipStart != null || clipEnd != null) && (
            <button onClick={() => { setClipStart(null); setClipEnd(null); }} className={styles.trimReset}>{'✕'}</button>
          )}
        </div>
      )}
      <div className={styles.searchRow}>
        <TextInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery('')}
          clearLabel="поиск"
          placeholder={audioUrl ? 'Поиск по словам… (клик по реплике — перемотка)' : 'Поиск по словам…'}
          className={styles.searchField}
          inputClassName={styles.search}
        />
        {q && <span className={styles.count}>{filtered.length} из {segments.length}</span>}
      </div>
      <div ref={listRef} className={styles.segList}>
        {q && filtered.length === 0 && <div className={styles.empty}>Ничего не найдено</div>}
        {renderedSegments}
      </div>
    </>
  );
};
