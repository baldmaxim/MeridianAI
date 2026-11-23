import { useId, useState } from 'react';
import type { FC, ReactNode } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { loadMultichannelShadowEnabled } from '../../audio/audioCaptureMetadata';
import { ChatDisplay } from '../../components/meeting/ChatDisplay';
import { ConversationTreePanel } from '../../components/meeting/ConversationTreePanel';
import { CustomerQuestionChat } from '../../components/meeting/CustomerQuestionChat';
import { MeetingStats } from '../../components/meeting/MeetingStats';
import { SpeakerIdentityReviewPanel } from '../../components/meeting/SpeakerIdentityReviewPanel';
import { SpeakerSideAssignmentPanel } from '../../components/meeting/SpeakerSideAssignmentPanel';
import type { TMeetingSpeakers } from './useMeetingSpeakers';
import styles from './MeetingSidePanel.module.css';

type TSideTab = 'transcript' | 'tree' | 'ask' | 'stats';

interface ISideTab {
  id: TSideTab;
  label: string;
}

interface IMeetingSidePanelProps {
  speakers: TMeetingSpeakers;
  /** Провайдер STT с диаризацией: можно менять число спикеров. */
  canSetMaxSpeakers: boolean;
  onSaveToHistory: () => void;
}

const SIDE_TABS: readonly ISideTab[] = [
  { id: 'transcript', label: 'Транскрипт' },
  { id: 'tree', label: 'Дерево' },
  { id: 'ask', label: 'Вопрос Заказчика' },
  { id: 'stats', label: 'Динамика' },
];

const TAB_STORAGE_KEY = 'meridian:meeting-side-tab';
const SPEAKERS_OPEN_KEY = 'meridian:meeting-speakers-open';

const readStorage = (key: string): string | null => {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
};

const writeStorage = (key: string, value: string) => {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* localStorage недоступен — выбор живёт до перезагрузки */
  }
};

const readStoredTab = (): TSideTab => {
  const stored = readStorage(TAB_STORAGE_KEY);
  return SIDE_TABS.find((t) => t.id === stored)?.id ?? 'transcript';
};

/** Единая правая панель встречи: транскрипт со спикерами, дерево общения, «Вопрос Заказчика», динамика. */
export const MeetingSidePanel: FC<IMeetingSidePanelProps> = ({ speakers, canSetMaxSpeakers, onSaveToHistory }) => {
  const baseId = useId();
  const [active, setActive] = useState<TSideTab>(readStoredTab);
  const [speakersOpen, setSpeakersOpen] = useState(() => readStorage(SPEAKERS_OPEN_KEY) !== '0');
  const currentMeetingId = useMeetingStore((s) => s.currentMeetingId);
  const canSendAudio = useMeetingStore((s) => s.canSendAudio);
  const messages = useMeetingStore((s) => s.messages);
  const multiChannelLiveState = useMeetingStore((s) => s.multiChannelLiveState);
  const treeCount = useMeetingStore((s) => s.conversationTree.length);

  const selectTab = (id: TSideTab) => {
    setActive(id);
    writeStorage(TAB_STORAGE_KEY, id);
  };

  const toggleSpeakers = () => {
    writeStorage(SPEAKERS_OPEN_KEY, speakersOpen ? '0' : '1');
    setSpeakersOpen(!speakersOpen);
  };

  const tabId = (id: TSideTab) => `${baseId}-tab-${id}`;
  const paneId = (id: TSideTab) => `${baseId}-pane-${id}`;

  // Все панели остаются смонтированными: переключение вкладки не сбрасывает историю чата и состояние сохранения.
  const renderPane = (id: TSideTab, className: string, content: ReactNode) => (
    <div
      key={id}
      id={paneId(id)}
      role="tabpanel"
      aria-labelledby={tabId(id)}
      hidden={active !== id}
      className={`${styles.pane} ${className}`}
    >
      {content}
    </div>
  );

  return (
    <div className={styles.root}>
      <div className={styles.tabList} role="tablist" aria-label="Разделы панели встречи">
        {SIDE_TABS.map((tab) => (
          <button
            key={tab.id}
            id={tabId(tab.id)}
            type="button"
            role="tab"
            aria-selected={active === tab.id}
            aria-controls={paneId(tab.id)}
            className={`t-btn ${styles.tab}${active === tab.id ? ` ${styles.tabActive}` : ''}`}
            onClick={() => selectTab(tab.id)}
          >
            {tab.label}
            {tab.id === 'tree' && treeCount > 0 && <span className={styles.badge}>{treeCount}</span>}
          </button>
        ))}
      </div>

      {renderPane('transcript', styles.paneTranscript, (
        <>
          <button
            type="button"
            className={styles.speakersToggle}
            aria-expanded={speakersOpen}
            onClick={toggleSpeakers}
          >
            <span className={`${styles.chevron}${speakersOpen ? ` ${styles.chevronOpen}` : ''}`}>▸</span>
            Спикеры и роли
          </button>
          <div className={styles.speakersBody} hidden={!speakersOpen}>
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
          </div>
          <ChatDisplay
            onSetSpeakerRole={speakers.handleSetSpeakerSide}
            onCorrectSegment={speakers.handleCorrectSegment}
            onSetSegmentCorrection={speakers.handleSetSegmentCorrection}
          />
        </>
      ))}
      {renderPane('tree', styles.paneTree, <ConversationTreePanel meetingId={currentMeetingId} />)}
      {renderPane('ask', styles.paneScroll, <CustomerQuestionChat key={currentMeetingId ?? 'none'} />)}
      {renderPane('stats', styles.paneScroll, <MeetingStats onSaveToHistory={onSaveToHistory} />)}
    </div>
  );
};
