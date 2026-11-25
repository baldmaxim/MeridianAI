import { useEffect, useRef, useState } from 'react';
import type { FC, RefObject, SyntheticEvent } from 'react';
import { AudioPlayer } from '../../components/common/AudioPlayer';
import { getMeetingAudio } from '../../api/history';
import type { MeetingAudioPart } from '../../types';
import { cx } from '../../utils/cx';
import styles from './MeetingAudioPlayer.module.css';

interface IMeetingAudioPlayerProps {
  meetingId: number;
  /** Внешний ref на audio — чтобы родитель мог перематывать запись; нет — свой внутренний. */
  audioRef?: RefObject<HTMLAudioElement | null>;
  /** true, когда загружена ровно одна часть без ошибки (время реплик сопоставимо с записью); иначе false. */
  onSeekableChange?: (seekable: boolean) => void;
}

interface IResume {
  time: number;
  wasPlaying: boolean;
}

/** Ответ для конкретной встречи: части, null (записи нет) или 'error'. */
interface ILoaded {
  meetingId: number;
  parts: MeetingAudioPart[] | null | 'error';
}

/** Плеер записи прошедшей встречи: части (batch/архив ПК/живая запись) переключаются чипами. */
export const MeetingAudioPlayer: FC<IMeetingAudioPlayerProps> = ({ meetingId, audioRef: externalRef, onSeekableChange }) => {
  const [loaded, setLoaded] = useState<ILoaded | null>(null);
  const [activeFor, setActiveFor] = useState<{ meetingId: number; index: number }>({ meetingId, index: 0 });
  const innerRef = useRef<HTMLAudioElement>(null);
  const audioRef = externalRef ?? innerRef;
  // Один перезапрос ссылок на «серию» ошибок; сбрасывается, когда запись снова загрузилась
  const retriedRef = useRef(false);
  const resumeRef = useRef<IResume | null>(null);

  useEffect(() => {
    let cancelled = false;
    retriedRef.current = false;
    resumeRef.current = null;
    getMeetingAudio(meetingId)
      .then((res) => { if (!cancelled) setLoaded({ meetingId, parts: res && res.length > 0 ? res : null }); })
      .catch(() => { if (!cancelled) setLoaded({ meetingId, parts: 'error' }); });
    return () => { cancelled = true; };
  }, [meetingId]);

  // Данные/выбор от другой встречи считаем устаревшими (без setState в эффекте)
  const current = loaded && loaded.meetingId === meetingId ? loaded.parts : undefined;
  const parts = Array.isArray(current) ? current : [];
  const active = activeFor.meetingId === meetingId ? activeFor.index : 0;

  // Перемотка по репликам возможна только при одной части записи (время частей не сопоставлено)
  const seekable = Array.isArray(current) && current.length === 1;
  useEffect(() => {
    onSeekableChange?.(seekable);
    return () => onSeekableChange?.(false);
  }, [seekable, onSeekableChange]);

  const handleError = async () => {
    const audio = audioRef.current;
    if (retriedRef.current) {
      setLoaded({ meetingId, parts: 'error' });
      return;
    }
    retriedRef.current = true;
    resumeRef.current = audio ? { time: audio.currentTime, wasPlaying: !audio.paused } : null;
    try {
      const res = await getMeetingAudio(meetingId);
      setLoaded({ meetingId, parts: res && res.length > 0 ? res : 'error' });
    } catch {
      setLoaded({ meetingId, parts: 'error' });
    }
  };

  const handleLoaded = (e: SyntheticEvent<HTMLAudioElement>) => {
    retriedRef.current = false;
    const resume = resumeRef.current;
    resumeRef.current = null;
    if (!resume) return;
    const audio = e.currentTarget;
    if (resume.time > 0) audio.currentTime = resume.time;
    if (resume.wasPlaying) audio.play().catch(() => { /* автозапуск мог быть запрещён браузером */ });
  };

  const selectPart = (i: number) => {
    resumeRef.current = null;
    retriedRef.current = false;
    setActiveFor({ meetingId, index: i });
  };

  if (current === undefined || current === null) return null;
  if (current === 'error') return <div className={styles.unavailable}>Запись недоступна</div>;

  const part = parts[Math.min(active, parts.length - 1)];

  return (
    <div className={styles.player}>
      {parts.length > 1 && (
        <div className={styles.chips} role="group" aria-label="Части записи">
          {parts.map((p, i) => (
            <button
              key={p.url}
              type="button"
              aria-pressed={i === active}
              onClick={() => selectPart(i)}
              className={cx(styles.chip, i === active && styles.chipActive)}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}
      <AudioPlayer
        ref={audioRef}
        preload="metadata"
        src={part.url}
        aria-label="Запись встречи"
        onError={handleError}
        onLoadedMetadata={handleLoaded}
      />
    </div>
  );
};
