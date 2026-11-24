import type { FC } from 'react';
import { ProtocolPane } from '../../components/protocol/ProtocolPane';
import { toPublicSpeakerSide } from '../../lib/speakerSides';
import type { SpeakerRoleOut, TranscriptSegmentRecord } from '../../types';
import { cx } from '../../utils/cx';
import { segmentSpeakerKey } from './speakerList';
import { SpeakersEditor } from './SpeakersEditor';
import { TranscriptRow } from './TranscriptRow';
import styles from './MeetingMainWindow.module.css';

export type TMainTab = 'transcript' | 'protocol';

interface IMeetingMainWindowProps {
  meetingId: number;
  segments: TranscriptSegmentRecord[];
  rolesByLabel: Map<string, SpeakerRoleOut>;
  tab: TMainTab;
  onTabChange: (tab: TMainTab) => void;
  /** Сегмент «Транскрипт | Протокол» вверху окна (на узких экранах вкладки — на странице). */
  showSwitch: boolean;
  protocolRefresh: number;
  onRolesChange: (roles: SpeakerRoleOut[]) => void;
  onProtocolRebuild: () => void;
}

const TABS: ReadonlyArray<{ key: TMainTab; label: string }> = [
  { key: 'transcript', label: 'Транскрипт' },
  { key: 'protocol', label: 'Протокол' },
];

/** Главное окно прошедшей встречи: полоса спикеров, вкладки «Транскрипт»/«Протокол» со слайдом (transitions.dev 08). */
export const MeetingMainWindow: FC<IMeetingMainWindowProps> = ({
  meetingId, segments, rolesByLabel, tab, onTabChange, showSwitch,
  protocolRefresh, onRolesChange, onProtocolRebuild,
}) => (
  <section className={styles.window}>
    {showSwitch && (
      <div className={styles.head}>
        <div className={styles.switch} role="tablist" aria-label="Содержимое встречи">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={cx(styles.switchBtn, tab === key && styles.switchBtnActive)}
              onClick={() => onTabChange(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className={styles.meta}>{segments.length} сегментов</span>
      </div>
    )}

    {/* Имена и стороны спикеров + пересборка протокола (при пустой транскрипции не рисуется) */}
    <SpeakersEditor
      meetingId={meetingId}
      segments={segments}
      onRolesChange={onRolesChange}
      onProtocolRebuild={onProtocolRebuild}
    />

    <div className={cx('t-page-slide', styles.pages)} data-page={tab === 'transcript' ? 1 : 2}>
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
