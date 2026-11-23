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
      {/* Источники контекста: дерево слева на десктопе, под краткими настройками на узких экранах */}
      <section className={styles.sourcesCol}>
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
      </section>

      <aside className={styles.settingsCol}>
        <div className={styles.settingsScroll}>
          {currentMeetingId != null && (
            <div className={styles.roomStatus}>
              <span className={styles.roomBadge}>
                <span className={roomDotClass} />
                {roomConnected ? (recording ? 'REC' : 'online') : 'offline'}
              </span>
              <span>ID: <b className={styles.strong}>{currentMeetingId}</b></span>
              <span>·</span>
              <span>Room: <b className={roomConnected ? styles.on : styles.off}>{roomConnected ? 'connected' : 'offline'}</b></span>
              <span>·</span>
              <span>
                Audio: <b className={recording ? styles.on : styles.off}>
                  {recording ? (deviceRole || 'устройство') : 'none'}
                </b>
              </span>
            </div>
          )}

          {/* Краткие настройки: название, тема, тип, роль, ключевые условия */}
          <div className={styles.field}>
            <label className={styles.label} htmlFor="meeting-name-input">Название</label>
            <TextInput
              id="meeting-name-input"
              type="text"
              placeholder="Название встречи"
              value={meetingName}
              onChange={(e) => onMeetingNameChange(e.target.value)}
              onClear={() => onMeetingNameChange('')}
              clearLabel="название встречи"
              inputClassName={styles.fieldInput}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="meeting-topic-input">Тема / цель</label>
            <TextInput
              id="meeting-topic-input"
              type="text"
              placeholder="Тема / цель встречи"
              value={meetingTopic}
              onChange={(e) => onMeetingTopicChange(e.target.value)}
              onClear={() => onMeetingTopicChange('')}
              clearLabel="тему встречи"
              inputClassName={styles.fieldInput}
            />
          </div>

          <MeetingContext pushContext={pushContext}>
            {/* Активная роль (live, через WS change_role) */}
            <div className={styles.field}>
              <span className={styles.label}>Активная роль</span>
              <RoleSelector onRoleSelect={onRoleSelect} />
            </div>
          </MeetingContext>

          {/* Расширенные настройки — свёрнуты */}
          <CollapsibleSection title="Расширенные настройки" flat>
            {ctxMeetingId != null && <MeetingAISettingsBlock meetingId={ctxMeetingId} />}

            <CollapsibleSection title="Слабые стороны оппонента" flat>
              <textarea
                placeholder={"Известные проблемы, сорванные сроки, рыночная позиция..."}
                value={opponentWeaknesses}
                onChange={(e) => onWeaknessesChange(e.target.value)}
                rows={3}
                className={styles.weakTextarea}
              />
            </CollapsibleSection>

            {/* Этап 5: итоги встречи / протокол */}
            <FinalizationPanel meetingId={currentMeetingId} onFinalized={onFinalized} />
          </CollapsibleSection>
        </div>

        <div className={styles.saveBar}>
          <button
            className={`save-meeting-btn t-btn t-btn-amber ${styles.saveMeetingBtn}`}
            onClick={onSaveMeeting}
            disabled={savingMeeting}
          >
            {savingMeeting ? 'Сохранение...' : 'Сохранить встречу'}
          </button>
        </div>
      </aside>
    </div>
  );
};
