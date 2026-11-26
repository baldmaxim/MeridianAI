import { useCallback, useMemo, useRef, useState } from 'react';
import type { FC } from 'react';
import { ProtocolPane } from '../../components/protocol/ProtocolPane';
import { toPublicSpeakerSide } from '../../lib/speakerSides';
import type { SpeakerRoleOut, TranscriptSegmentRecord } from '../../types';
import { cx } from '../../utils/cx';
import { segmentSpeakerKey } from './speakerList';
import { SpeakersEditor } from './SpeakersEditor';
import { TranscriptRow } from './TranscriptRow';
import { MeetingAudioPlayer } from './MeetingAudioPlayer';
import { MainTabSwitch } from './MainTabSwitch';
import type { TMainTab } from './MainTabSwitch';
import { useActiveSegment } from './useActiveSegment';
import { useHorizontalSwipe } from './useHorizontalSwipe';
import styles from './MeetingMainWindow.module.css';

export type { TMainTab };

interface IMeetingMainWindowProps {
  meetingId: number;
  segments: TranscriptSegmentRecord[];
  rolesByLabel: Map<string, SpeakerRoleOut>;
  tab: TMainTab;
  onTabChange: (tab: TMainTab) => void;
  /** Сегмент «Транскрипт | Протокол» вверху окна (на узких экранах вкладки — на странице). */
  showSwitch: boolean;
  /** Встреча завершена (ended_at или status = finalized) — тогда над вкладками показывается плеер записи. */
  ended: boolean;
  protocolRefresh: number;
  onRolesChange: (roles: SpeakerRoleOut[]) => void;
  onProtocolRebuild: () => void;
}

/** Главное окно прошедшей встречи: полоса спикеров, вкладки «Транскрипт»/«Протокол» со слайдом (transitions.dev 08). */
export const MeetingMainWindow: FC<IMeetingMainWindowProps> = ({
  meetingId, segments, rolesByLabel, tab, onTabChange, showSwitch, ended,
  protocolRefresh, onRolesChange, onProtocolRebuild,
}) => {
  // Свайп влево — к протоколу, вправо — к транскрипту
  const swipe = useHorizontalSwipe((dir) => onTabChange(dir === 'left' ? 'protocol' : 'transcript'));

  // Перемотка записи по клику на реплику: только при одной части записи
  const audioRef = useRef<HTMLAudioElement>(null);
  const [seekable, setSeekable] = useState(false);
  const starts = useMemo(() => segments.map((s) => s.start_time), [segments]);
  const activeIdx = useActiveSegment(audioRef, starts, seekable);
  const seekTo = useCallback((start: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = start;
    audio.play().catch(() => { /* автозапуск мог быть запрещён браузером — перемотка уже выполнена */ });
  }, []);

  return (
    <section className={styles.window}>
      {showSwitch && (
        <div className={styles.head}>
          <MainTabSwitch tab={tab} onChange={onTabChange} />
          <span className={styles.meta}>{segments.length} сегментов</span>
        </div>
      )}

      {/* Запись встречи: над обеими вкладками; нет записи — не рисуется */}
      {ended && <MeetingAudioPlayer meetingId={meetingId} audioRef={audioRef} onSeekableChange={setSeekable} />}

      {/* Имена и стороны спикеров + пересборка протокола (при пустой транскрипции не рисуется) */}
      <SpeakersEditor
        meetingId={meetingId}
        segments={segments}
        onRolesChange={onRolesChange}
        onProtocolRebuild={onProtocolRebuild}
      />

      <div className={cx('t-page-slide', styles.pages)} {...swipe} data-page={tab === 'transcript' ? 1 : 2}>
        <div className={cx('t-page', styles.page)} data-page-id="1" inert={tab !== 'transcript'}>
          {segments.length === 0 ? (
            <div className={styles.empty}>Нет данных транскрипции</div>
          ) : segments.map((seg, i) => {
            const role = rolesByLabel.get(segmentSpeakerKey(seg));
            return (
              <TranscriptRow
                key={seg.segment_id || i}
                segment={seg}
                speakerName={role?.display_name}
                side={toPublicSpeakerSide(role?.side) || null}
                active={i === activeIdx}
                audioRef={seekable ? audioRef : undefined}
                onSeek={seekable ? () => seekTo(seg.start_time) : undefined}
              />
            );
          })}
        </div>
        <div className={cx('t-page', styles.pageProtocol)} data-page-id="2" inert={tab !== 'protocol'}>
          <ProtocolPane meetingId={meetingId} refreshKey={protocolRefresh} />
        </div>
      </div>
    </section>
  );
};
