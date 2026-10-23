import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { ragContextApiAdapter } from '../../api/ragContextAdapter';
import { CollapsibleSection, TextInput } from '../../components/common';
import { SourcesPanel } from '../../components/context/SourcesPanel';
import { MeetingAISettingsBlock } from '../../components/context/MeetingAISettings';
import { MeetingContext } from '../../components/context/MeetingContext';
import { RoleSelector } from '../../components/context/RoleSelector';
import { FinalizationPanel } from '../../components/protocol/FinalizationPanel';
import styles from './MeetingContextTab.module.css';

interface IMeetingContextTabProps {
  pushContext: () => void;
  onMeetingNameChange: (name: string) => void;
  onMeetingTopicChange: (topic: string) => void;
  onWeaknessesChange: (value: string) => void;
  onRoleSelect: (roleId: number) => void;
  onSaveMeeting: () => void;
  savingMeeting: boolean;
  onFinalized: () => void;
  /** Вернуть id текущей встречи или создать её (null — не удалось). */
  startSession: (forceNew?: boolean) => Promise<number | null>;
}

/** Вкладка «Контекст встречи»: брифинг, источники контекста, расширенные настройки. */
export const MeetingContextTab: FC<IMeetingContextTabProps> = ({
  pushContext, onMeetingNameChange, onMeetingTopicChange, onWeaknessesChange, onRoleSelect,
  onSaveMeeting, savingMeeting, onFinalized, startSession,
}) => {
  const currentMeetingId = useMeetingStore((s) => s.currentMeetingId);
  const draftMeetingId = useMeetingStore((s) => s.draftMeetingId);
  const roomConnected = useMeetingStore((s) => s.roomConnected);
  const recording = useMeetingStore((s) => s.recording);
  const deviceRole = useMeetingStore((s) => s.deviceRole);
  const meetingName = useMeetingStore((s) => s.meetingName);
  const meetingTopic = useMeetingStore((s) => s.meetingTopic);
  const opponentWeaknesses = useMeetingStore((s) => s.opponentWeaknesses);
  const selectedCustomerId = useMeetingStore((s) => s.selectedCustomerId);
  const selectedObjectId = useMeetingStore((s) => s.selectedObjectId);

  const ctxMeetingId = currentMeetingId ?? draftMeetingId ?? null;
  const roomDotClass = `${styles.roomDot} ${roomConnected ? styles.dotOn : styles.dotOff}`;

  return (
    <div className={`mobile-content-pad ${styles.contextPanel}`}>
      <header className={styles.head}>
        <TextInput
          type="text"
          aria-label="Название встречи"
          placeholder="Название встречи"
          value={meetingName}
          onChange={(e) => onMeetingNameChange(e.target.value)}
          onClear={() => onMeetingNameChange('')}
          clearLabel="название встречи"
          inputClassName={styles.titleInput}
        />
        <TextInput
          type="text"
          aria-label="Тема / цель встречи"
          placeholder="Тема / цель встречи"
          value={meetingTopic}
          onChange={(e) => onMeetingTopicChange(e.target.value)}
          onClear={() => onMeetingTopicChange('')}
          clearLabel="тему встречи"
          inputClassName={styles.topicInput}
        />
        {currentMeetingId != null && (
          <div className={styles.roomStatus}>
            <span className={styles.roomBadge}>
              <span className={roomDotClass} />
              {roomConnected ? (recording ? 'REC' : 'online') : 'offline'}
            </span>
            <span>Meeting ID: <b className={styles.strong}>{currentMeetingId}</b></span>
            <span>·</span>
            <span>Room: <b className={roomConnected ? styles.on : styles.off}>{roomConnected ? 'connected' : 'offline'}</b></span>
            <span>·</span>
            <span>
              Active audio: <b className={recording ? styles.on : styles.off}>
                {recording ? (deviceRole || 'устройство') : 'none'}
              </b>
            </span>
          </div>
        )}
      </header>

      <aside className={styles.sourcesCol}>
        {/* Источники контекста: слева на десктопе, над формой на узких экранах */}
        <SourcesPanel
          meetingId={ctxMeetingId}
          customerId={selectedCustomerId}
          objectId={selectedObjectId}
          ensureMeetingId={async () => {
            const st = useMeetingStore.getState();
            if (st.currentMeetingId != null) return st.currentMeetingId;
            return await startSession(false);
          }}
          ragAdapter={ragContextApiAdapter}
        />
      </aside>

      <div className={styles.mainCol}>
        {/* Краткие настройки — тип переговоров + ключевые условия */}
        <CollapsibleSection title="Краткие настройки" defaultOpen>
          <MeetingContext pushContext={pushContext} />
        </CollapsibleSection>

        {/* C. Расширенные настройки */}
        <CollapsibleSection title="Расширенные настройки">
          {/* AI-настройки встречи */}
          {ctxMeetingId != null && <MeetingAISettingsBlock meetingId={ctxMeetingId} />}

          {/* Слабые стороны оппонента */}
          <CollapsibleSection title="Слабые стороны оппонента">
            <textarea
              placeholder={"Известные проблемы, сорванные сроки, рыночная позиция..."}
              value={opponentWeaknesses}
              onChange={(e) => onWeaknessesChange(e.target.value)}
              rows={3}
              className={styles.weakTextarea}
            />
          </CollapsibleSection>

          {/* Активная роль (live, через WS change_role) */}
          <div className={styles.contextCard}>
            <div className={styles.sectionHeader}>
              <span className={styles.dot} />
              <span className={styles.sectionTitle}>Активная роль (для подсказок)</span>
            </div>
            <RoleSelector onRoleSelect={onRoleSelect} />
          </div>

          {/* Сохранить встречу */}
          <div className={styles.saveRow}>
            <button
              className={`save-meeting-btn t-btn t-btn-amber ${styles.saveMeetingBtn}`}
              onClick={onSaveMeeting}
              disabled={savingMeeting}
            >
              {savingMeeting ? 'Сохранение...' : 'Сохранить встречу'}
            </button>
          </div>

          {/* Этап 5: итоги встречи / протокол */}
          <FinalizationPanel meetingId={currentMeetingId} onFinalized={onFinalized} />
        </CollapsibleSection>
      </div>
    </div>
  );
};
