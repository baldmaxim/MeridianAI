import { useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { SuggestionPanel } from '../../components/meeting/SuggestionPanel';
import { CustomerQuestionChat } from '../../components/meeting/CustomerQuestionChat';
import styles from './MeetingMainPanel.module.css';

type TMainMode = 'suggestions' | 'chat';

const MODE_KEY = 'meridian:meeting-main-mode';

const MODES: readonly { id: TMainMode; label: string }[] = [
  { id: 'suggestions', label: 'AI подсказки' },
  { id: 'chat', label: 'Чат' },
];

const readMode = (): TMainMode => {
  try {
    return window.localStorage.getItem(MODE_KEY) === 'chat' ? 'chat' : 'suggestions';
  } catch {
    return 'suggestions';
  }
};

/** Главная (левая) панель встречи: переключатель «AI подсказки | Чат» («Вопрос Заказчика» на всю панель). */
export const MeetingMainPanel: FC = () => {
  const [mode, setMode] = useState<TMainMode>(readMode);
  const currentMeetingId = useMeetingStore((s) => s.currentMeetingId);

  const select = (next: TMainMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(MODE_KEY, next);
    } catch {
      /* localStorage недоступен — выбор живёт до перезагрузки */
    }
  };

  return (
    <div className={styles.root}>
      <div className={styles.seg} role="group" aria-label="Что показывать в главной панели">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            aria-pressed={mode === m.id}
            className={`t-btn ${styles.segBtn}${mode === m.id ? ` ${styles.segActive}` : ''}`}
            onClick={() => select(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>
      {/* Обе панели остаются смонтированными: переключение не сбрасывает историю чата */}
      <div className={styles.pane} hidden={mode !== 'suggestions'}>
        <SuggestionPanel />
      </div>
      <div className={`${styles.pane} ${styles.chatPane}`} hidden={mode !== 'chat'}>
        <CustomerQuestionChat key={currentMeetingId ?? 'none'} />
      </div>
    </div>
  );
};
