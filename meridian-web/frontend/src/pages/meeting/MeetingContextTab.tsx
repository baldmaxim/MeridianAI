import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { ragContextApiAdapter } from '../../api/ragContextAdapter';
import { CollapsibleSection, TextInput } from '../../components/common';
import { ContextBasket } from '../../components/context/ContextBasket';
import { MeetingAISettingsBlock } from '../../components/context/MeetingAISettings';
import { MeetingContext } from '../../components/context/MeetingContext';
import { RoleSelector } from '../../components/context/RoleSelector';
import { FinalizationPanel } from '../../components/protocol/FinalizationPanel';
import styles from './MeetingContextTab.module.css';

interface IMeetingContextTabProps {
  pushContext: () => void;
  onMeetingNameChange: (name: string) => void;
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
  pushContext, onMeetingNameChange, onWeaknessesChange, onRoleSelect,
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
      {/* A. Брифинг встречи: две сбалансированные карточки рядом */}
      <div className={`context-columns ${styles.briefGrid}`}>
        {/* Встреча — название/тема (стек) + статус */}
        <div className={styles.contextCard}>
          <div className={styles.sectionHeader}>
            <span className={styles.dot} />
            <span className={styles.sectionTitle}>Встреча</span>
            {currentMeetingId != null && (
              <span className={styles.roomBadge}>
                <span className={roomDotClass} />
                {roomConnected ? (recording ? 'REC' : 'online') : 'offline'}
              </span>
            )}
          </div>

          <div className={styles.meetingField}>
            <label className={styles.miniLabel}>Название встречи</label>
            <TextInput
              type="text"
              placeholder="Например: Переговоры с заказчиком ЖК Рассвет"
              value={meetingName}
              onChange={(e) => onMeetingNameChange(e.target.value)}
              onClear={() => onMeetingNameChange('')}
              clearLabel="название встречи"
            />
          </div>
          <div className={styles.meetingField}>
            <label className={styles.miniLabel}>Тема / цель встречи</label>
            <TextInput
              type="text"
              readOnly
              placeholder="Сформируется автоматически после завершения встречи"
              value={meetingTopic}
              title="Краткое наименование формируется ИИ после распознавания всех переговоров"
              className={styles.readonlyField}
              clearLabel="тему встречи"
            />
          </div>

          {currentMeetingId != null && (
            <div className={styles.roomStatus}>
              <span className={styles.roomStatusItem}>Meeting ID: <b className={styles.strong}>{currentMeetingId}</b></span>
              <span className={styles.roomStatusItem}>
                <span className={roomDotClass} />
                {roomConnected ? 'Room connected' : 'Room offline'}
              </span>
              <span className={styles.roomStatusItem}>
                Active audio: <b className={recording ? styles.on : styles.off}>
                  {recording ? (deviceRole || 'устройство') : 'none'}
                </b>
              </span>
            </div>
          )}
        </div>

        {/* Краткие настройки — тип переговоров + ключевые условия */}
        <CollapsibleSection title="Краткие настройки" defaultOpen>
          <MeetingContext pushContext={pushContext} />
        </CollapsibleSection>
      </div>

      {/* B. Источники контекста — на всю ширину */}
      <ContextBasket
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
  );
};
