import type { CSSProperties, FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { PopNumber } from '../../components/common/PopNumber';
import { ResizeHandle } from '../../components/common/ResizeHandle';
import { SpeakersColumn } from '../../components/meeting/SpeakersColumn';
import { SpeakersPanel } from '../../components/meeting/SpeakersPanel';
import { useMediaQuery } from '../../hooks/useMediaQuery';
import { useResizableWidth } from '../../hooks/useResizableWidth';
import { MeetingMainPanel } from './MeetingMainPanel';
import { MeetingSidePanel } from './MeetingSidePanel';
import type { TMeetingSpeakers } from './useMeetingSpeakers';
import styles from './NegotiationsTab.module.css';

interface INegotiationsTabProps {
  drawerOpen: boolean;
  onCloseDrawer: () => void;
  speakers: TMeetingSpeakers;
  /** Провайдер STT с диаризацией: можно менять число спикеров. */
  canSetMaxSpeakers: boolean;
}

// v2: панель стала единой и шире — старая сохранённая ширина (260) не должна её сужать
const PANEL_WIDTH_KEY = 'meridian:meeting-right-panel-width-v2';
const PANEL_MIN_PX = 300;
const PANEL_DEFAULT_PX = 420;
const PANEL_MAX_RATIO = 0.6;
const getPanelMaxPx = (): number => Math.round(window.innerWidth * PANEL_MAX_RATIO);

/** От этой ширины спикеры — отдельная колонка справа; ниже — вкладка «Спикеры» в правой панели. */
const SPEAKERS_COLUMN_QUERY = '(min-width: 1024px)';

/**
 * Вкладка «Переговоры»: слева подсказки/чат, справа панель «Транскрипт | Дерево»
 * и колонка «Спикеры» (bottom sheet на телефонах).
 */
export const NegotiationsTab: FC<INegotiationsTabProps> = ({
  drawerOpen, onCloseDrawer, speakers, canSetMaxSpeakers,
}) => {
  const meetingStats = useMeetingStore((s) => s.meetingStats);
  const canSendAudio = useMeetingStore((s) => s.canSendAudio);
  const speakersAsColumn = useMediaQuery(SPEAKERS_COLUMN_QUERY);
  const speakersProps = {
    onSetSpeakerSide: speakers.handleSetSpeakerSide,
    onSetSpeakerName: speakers.handleSetSpeakerName,
    onSetMaxSpeakers: canSendAudio && canSetMaxSpeakers ? speakers.handleMaxSpeakersChange : undefined,
  };
  const panel = useResizableWidth({
    storageKey: PANEL_WIDTH_KEY, min: PANEL_MIN_PX, max: getPanelMaxPx, defaultWidth: PANEL_DEFAULT_PX, side: 'left',
  });

  return (
    <div className={styles.wrap}>
      {/* Mobile stats strip */}
      <div className="mobile-stats-strip">
        <div className="stat-chip">
          <div className={`stat-chip-val ${meetingStats.positionStrength >= 60 ? styles.good : styles.warn}`}>
            <PopNumber value={`${meetingStats.positionStrength}%`} />
          </div>
          <div className="stat-chip-lbl">Позиция</div>
        </div>
        <div className="stat-chip">
          <div className={`stat-chip-val ${styles.good}`}>
            <PopNumber value={meetingStats.suggestionsUsed} />
          </div>
          <div className="stat-chip-lbl">Принято</div>
        </div>
        <div className="stat-chip">
          <div className={`stat-chip-val ${meetingStats.activeObjections > 0 ? styles.bad : styles.neutral}`}>
            <PopNumber value={meetingStats.activeObjections} />
          </div>
          <div className="stat-chip-lbl">Возраж.</div>
        </div>
      </div>

      <div className={`meeting-layout ${styles.meetingLayout}`}>
        {/* Left: AI-подсказки / чат на всю высоту */}
        <div className={styles.leftPanel}>
          <MeetingMainPanel />
        </div>
        {/* Right: единая панель с вкладками (bottom sheet на мобильных) */}
        {drawerOpen && <div className="drawer-backdrop" onClick={onCloseDrawer} />}
        <div
          className={`meeting-right-panel${drawerOpen ? ' drawer-open' : ''} ${styles.rightPanel}`}
          style={{ '--panel-w': `${panel.width}px` } as CSSProperties}
        >
          <ResizeHandle resizable={panel} className={styles.resizeHandle} label="Ширина правой панели" />
          <div className="sheet-handle-row">
            <div className={styles.sheetSpacer} />
            <div className="sheet-title">
              <span className="sheet-dot" />
              Панель встречи
            </div>
            <button className="sheet-close t-btn" onClick={onCloseDrawer} aria-label="Закрыть панель">&times;</button>
          </div>
          <MeetingSidePanel
            speakers={speakers}
            speakersTab={speakersAsColumn ? undefined : <SpeakersPanel variant="tab" {...speakersProps} />}
          />
        </div>
        {speakersAsColumn && <SpeakersColumn {...speakersProps} />}
      </div>
    </div>
  );
};
