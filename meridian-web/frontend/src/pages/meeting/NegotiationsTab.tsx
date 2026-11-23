import type { CSSProperties, FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { loadMultichannelShadowEnabled } from '../../audio/audioCaptureMetadata';
import { CollapsibleSection } from '../../components/common/CollapsibleSection';
import { PopNumber } from '../../components/common/PopNumber';
import { ResizeHandle } from '../../components/common/ResizeHandle';
import { ChatDisplay } from '../../components/meeting/ChatDisplay';
import { ConversationTreePanel } from '../../components/meeting/ConversationTreePanel';
import { CustomerQuestionChat } from '../../components/meeting/CustomerQuestionChat';
import { MeetingStats } from '../../components/meeting/MeetingStats';
import { SpeakerIdentityReviewPanel } from '../../components/meeting/SpeakerIdentityReviewPanel';
import { SpeakerSideAssignmentPanel } from '../../components/meeting/SpeakerSideAssignmentPanel';
import { SuggestionPanel } from '../../components/meeting/SuggestionPanel';
import { useResizableWidth } from '../../hooks/useResizableWidth';
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

const PANEL_WIDTH_KEY = 'meridian:meeting-right-panel-width';
const PANEL_MIN_PX = 240;
const PANEL_DEFAULT_PX = 260;
const PANEL_MAX_RATIO = 0.6;
const getPanelMaxPx = (): number => Math.round(window.innerWidth * PANEL_MAX_RATIO);

/** Вкладка «Переговоры»: подсказки, транскрипт (bottom sheet на мобильных), дерево общения. */
export const NegotiationsTab: FC<INegotiationsTabProps> = ({
  drawerOpen, onCloseDrawer, speakers, canSetMaxSpeakers, onSaveToHistory,
}) => {
  const meetingStats = useMeetingStore((s) => s.meetingStats);
  const currentMeetingId = useMeetingStore((s) => s.currentMeetingId);
  const canSendAudio = useMeetingStore((s) => s.canSendAudio);
  const messages = useMeetingStore((s) => s.messages);
  const multiChannelLiveState = useMeetingStore((s) => s.multiChannelLiveState);
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
        {/* Left: suggestions (wide) */}
        <div className={styles.leftPanel}>
          <SuggestionPanel />
          <div className={styles.askBlock}>
            <CollapsibleSection title="Вопрос Заказчика" defaultOpen>
              <CustomerQuestionChat key={currentMeetingId ?? 'none'} />
            </CollapsibleSection>
          </div>
        </div>
        {/* Right: transcript (bottom sheet on mobile) */}
        {drawerOpen && <div className="drawer-backdrop" onClick={onCloseDrawer} />}
        <div
          className={`meeting-right-panel${drawerOpen ? ' drawer-open' : ''} ${styles.rightPanel}`}
          style={{ '--panel-w': `${panel.width}px` } as CSSProperties}
        >
          <ResizeHandle resizable={panel} className={styles.resizeHandle} label="Ширина панели транскрипта" />
          <div className="sheet-handle-row">
            <div className={styles.sheetSpacer} />
            <div className="sheet-title">
              <span className="sheet-dot" />
              Транскрипция
            </div>
            <button className="sheet-close t-btn" onClick={onCloseDrawer}>&times;</button>
          </div>
          <SpeakerSideAssignmentPanel
            meetingId={currentMeetingId}
            canEdit={canSendAudio}
            compact
            onSetSpeakerSide={speakers.handleSetSpeakerSide}
            onSetSpeakerName={speakers.handleSetSpeakerName}
            onSetMaxSpeakers={canSendAudio && canSetMaxSpeakers ? speakers.handleMaxSpeakersChange : undefined}
          />
          <SpeakerIdentityReviewPanel
            meetingId={currentMeetingId}
            canEdit={canSendAudio}
            transcriptItems={messages}
            actualChannelCount={multiChannelLiveState?.channel_count ?? 0}
            multichannelShadowEnabled={loadMultichannelShadowEnabled()}
          />
          <ChatDisplay
            onSetSpeakerRole={speakers.handleSetSpeakerSide}
            onCorrectSegment={speakers.handleCorrectSegment}
            onSetSegmentCorrection={speakers.handleSetSegmentCorrection}
          />
          <MeetingStats onSaveToHistory={onSaveToHistory} />
        </div>
        {/* Third column: дерево общения (скрывается на узких экранах через CSS) */}
        <div className={`meeting-tree-panel ${styles.treePanel}`}>
          <ConversationTreePanel meetingId={currentMeetingId} />
        </div>
      </div>
    </div>
  );
};
