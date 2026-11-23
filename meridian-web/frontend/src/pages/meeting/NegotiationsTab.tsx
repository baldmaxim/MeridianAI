import type { CSSProperties, FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { PopNumber } from '../../components/common/PopNumber';
import { ResizeHandle } from '../../components/common/ResizeHandle';
import { SuggestionPanel } from '../../components/meeting/SuggestionPanel';
import { useResizableWidth } from '../../hooks/useResizableWidth';
import { MeetingSidePanel } from './MeetingSidePanel';
import type { TMeetingSpeakers } from './useMeetingSpeakers';
import styles from './NegotiationsTab.module.css';

interface INegotiationsTabProps {
  drawerOpen: boolean;
  onCloseDrawer: () => void;
  speakers: TMeetingSpeakers;
  /** Провайдер STT с диаризацией: можно менять число спикеров. */
  canSetMaxSpeakers: boolean;
  onSaveToHistory: () => void;
}

// v2: панель стала единой и шире — старая сохранённая ширина (260) не должна её сужать
const PANEL_WIDTH_KEY = 'meridian:meeting-right-panel-width-v2';
const PANEL_MIN_PX = 300;
const PANEL_DEFAULT_PX = 420;
const PANEL_MAX_RATIO = 0.6;
const getPanelMaxPx = (): number => Math.round(window.innerWidth * PANEL_MAX_RATIO);

/** Вкладка «Переговоры»: слева подсказки, справа единая панель с вкладками (bottom sheet на мобильных). */
export const NegotiationsTab: FC<INegotiationsTabProps> = ({
  drawerOpen, onCloseDrawer, speakers, canSetMaxSpeakers, onSaveToHistory,
}) => {
  const meetingStats = useMeetingStore((s) => s.meetingStats);
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
        {/* Left: AI-подсказки на всю высоту */}
        <div className={styles.leftPanel}>
          <SuggestionPanel />
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
            canSetMaxSpeakers={canSetMaxSpeakers}
            onSaveToHistory={onSaveToHistory}
          />
        </div>
      </div>
    </div>
  );
};
