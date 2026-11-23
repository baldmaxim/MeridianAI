import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { toPublicSpeakerSide } from '../../lib/speakerSides';
import type { PublicSpeakerSide } from '../../lib/speakerSides';
import type { FunctionalRole } from '../../features/speakerIdentity/speakerIdentityTypes';
import { Select } from '../common';
import { SpeakerCard } from './SpeakerCard';
import { useSpeakerList } from './useSpeakerList';
import { useSpeakerRoles } from './useSpeakerRoles';
import styles from './SpeakersPanel.module.css';

const MAX_SPEAKER_OPTIONS = [2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: String(n) }));

interface ISpeakersPanelHandlers {
  onSetSpeakerSide: (speaker: string, side: PublicSpeakerSide | '' | null) => void | Promise<void>;
  onSetSpeakerName: (speaker: string, displayName: string) => void | Promise<void>;
  /** undefined → число спикеров менять нельзя (нет диаризации / нет прав). */
  onSetMaxSpeakers?: (n: number) => void;
}

interface ISpeakersPanelProps extends ISpeakersPanelHandlers {
  /** column — отдельная колонка справа (есть «Скрыть»); tab — вкладка в узкой панели. */
  variant: 'column' | 'tab';
  onCollapse?: () => void;
}

/**
 * Единая панель «Спикеры»: число спикеров сверху, ниже — карточки распознанных голосов
 * (имя, сторона, роль). Данные и действия те же, что у прежних панелей идентификации.
 */
export const SpeakersPanel: FC<ISpeakersPanelProps> = ({
  variant, onCollapse, onSetSpeakerSide, onSetSpeakerName, onSetMaxSpeakers,
}) => {
  const meetingId = useMeetingStore((s) => s.currentMeetingId);
  const canEdit = useMeetingStore((s) => s.canSendAudio);
  const speakerRoles = useMeetingStore((s) => s.speakerRoles);
  const speakerNames = useMeetingStore((s) => s.speakerNames);
  const maxSpeakers = useMeetingStore((s) => s.maxSpeakers);
  const isListening = useMeetingStore((s) => s.isListening);
  const { speakers, assignedCount, unassignedCount } = useSpeakerList();
  const roles = useSpeakerRoles(meetingId, canEdit);

  const allAssigned = speakers.length > 0 && unassignedCount === 0;

  const handleSide = (label: string, side: PublicSpeakerSide | '') => {
    void onSetSpeakerSide(label, side);
    // сторона меняет и привязку роли: перепишем сохранённую роль под новую сторону
    const role = roles.roleOf(label);
    if (role !== 'unknown') roles.setRole(label, role, side);
  };

  const handleRole = (label: string, role: FunctionalRole) => {
    roles.setRole(label, role, toPublicSpeakerSide(speakerRoles[label]));
  };

  return (
    <section className={`${styles.panel} ${variant === 'tab' ? styles.panelTab : ''}`} aria-label="Спикеры">
      <header className={styles.head}>
        <span className={styles.title}>Спикеры</span>
        {speakers.length > 0 && (
          <span className={`${styles.counter} ${allAssigned ? styles.counterDone : ''}`}>
            {allAssigned ? 'Все назначены' : `Назначено ${assignedCount}/${speakers.length}`}
          </span>
        )}
        {variant === 'column' && onCollapse && (
          <button
            type="button"
            className={`t-btn ${styles.hideBtn} ${allAssigned ? styles.hideBtnReady : ''}`}
            onClick={onCollapse}
            title="Свернуть панель спикеров"
          >
            Скрыть
          </button>
        )}
      </header>

      {onSetMaxSpeakers && (
        <div className={styles.countRow}>
          <span className={styles.countLabel}>Ожидается спикеров</span>
          <Select
            value={String(maxSpeakers || 3)}
            onChange={(v) => onSetMaxSpeakers(Number(v))}
            options={MAX_SPEAKER_OPTIONS}
            triggerClassName={styles.countSelect}
            ariaLabel="Ожидаемое число спикеров"
          />
        </div>
      )}
      {onSetMaxSpeakers && isListening && (
        <div className={styles.countHint}>Применится сразу — распознавание перезапустится.</div>
      )}

      <div className={styles.list}>
        {speakers.length === 0 ? (
          <div className={styles.empty}>Спикеры появятся после первых реплик.</div>
        ) : (
          speakers.map((label) => (
            <SpeakerCard
              key={label}
              label={label}
              name={speakerNames[label] || ''}
              side={toPublicSpeakerSide(speakerRoles[label])}
              role={roles.roleOf(label)}
              canEdit={canEdit}
              roleEnabled={roles.ready && roles.canHaveRole(label) && toPublicSpeakerSide(speakerRoles[label]) !== ''}
              onSetName={(l, n) => void onSetSpeakerName(l, n)}
              onSetSide={handleSide}
              onSetRole={handleRole}
            />
          ))
        )}
      </div>
    </section>
  );
};
