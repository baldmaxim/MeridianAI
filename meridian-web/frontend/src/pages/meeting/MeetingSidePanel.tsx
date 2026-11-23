import { useId, useState } from 'react';
import type { FC, ReactNode } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { ChatDisplay } from '../../components/meeting/ChatDisplay';
import { ConversationTreePanel } from '../../components/meeting/ConversationTreePanel';
import { useSpeakerList } from '../../components/meeting/useSpeakerList';
import type { TMeetingSpeakers } from './useMeetingSpeakers';
import styles from './MeetingSidePanel.module.css';

type TSideTab = 'transcript' | 'tree' | 'speakers';

interface ISideTab {
  id: TSideTab;
  label: string;
}

interface IMeetingSidePanelProps {
  speakers: TMeetingSpeakers;
  /** Панель «Спикеры» как третья вкладка (<1024px); на широких экранах она отдельная колонка. */
  speakersTab?: ReactNode;
}

const TAB_STORAGE_KEY = 'meridian:meeting-side-tab';

const readStoredTab = (): string | null => {
  try {
    return window.localStorage.getItem(TAB_STORAGE_KEY);
  } catch {
    return null;
  }
};

const writeStoredTab = (value: string) => {
  try {
    window.localStorage.setItem(TAB_STORAGE_KEY, value);
  } catch {
    /* localStorage недоступен — выбор живёт до перезагрузки */
  }
};

/** Правая панель встречи: вкладки «Транскрипт | Дерево» (+ «Спикеры» на узких экранах). */
export const MeetingSidePanel: FC<IMeetingSidePanelProps> = ({ speakers, speakersTab }) => {
  const baseId = useId();
  const tabs: readonly ISideTab[] = [
    { id: 'transcript', label: 'Транскрипт' },
    { id: 'tree', label: 'Дерево' },
    ...(speakersTab ? [{ id: 'speakers' as const, label: 'Спикеры' }] : []),
  ];
  const [stored, setStored] = useState<string | null>(readStoredTab);
  // Сохранённая вкладка, которой сейчас нет (старые «Вопрос Заказчика»/«Динамика», «Спикеры» на десктопе), → транскрипт
  const active: TSideTab = tabs.find((t) => t.id === stored)?.id ?? 'transcript';
  const currentMeetingId = useMeetingStore((s) => s.currentMeetingId);
  const treeCount = useMeetingStore((s) => s.conversationTree.length);
  const { unassignedCount } = useSpeakerList();

  const selectTab = (id: TSideTab) => {
    setStored(id);
    writeStoredTab(id);
  };

  const tabId = (id: TSideTab) => `${baseId}-tab-${id}`;
  const paneId = (id: TSideTab) => `${baseId}-pane-${id}`;

  // Все панели остаются смонтированными: переключение вкладки не сбрасывает состояние.
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
        {tabs.map((tab) => (
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
            {tab.id === 'speakers' && unassignedCount > 0 && <span className={styles.badge}>{unassignedCount}</span>}
          </button>
        ))}
      </div>

      {renderPane('transcript', styles.paneTranscript, (
        <ChatDisplay
          onSetSpeakerRole={speakers.handleSetSpeakerSide}
          onCorrectSegment={speakers.handleCorrectSegment}
          onSetSegmentCorrection={speakers.handleSetSegmentCorrection}
        />
      ))}
      {renderPane('tree', styles.paneTree, <ConversationTreePanel meetingId={currentMeetingId} />)}
      {speakersTab && renderPane('speakers', styles.paneTree, speakersTab)}
    </div>
  );
};
