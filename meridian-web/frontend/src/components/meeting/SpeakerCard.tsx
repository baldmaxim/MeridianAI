import type { FC } from 'react';
import { Select } from '../common';
import { SpeakerNameInput } from './SpeakerNameInput';
import { ROLE_OPTIONS } from '../../features/speakerIdentity/speakerIdentityTypes';
import type { FunctionalRole } from '../../features/speakerIdentity/speakerIdentityTypes';
import type { PublicSpeakerSide } from '../../lib/speakerSides';
import styles from './SpeakersPanel.module.css';

const SIDE_CHOICES: { side: PublicSpeakerSide | ''; label: string }[] = [
  { side: 'self', label: 'Мы' },
  { side: 'opponent', label: 'Оппонент' },
  { side: '', label: 'Не знаю' },
];

const ROLE_SELECT_OPTIONS = ROLE_OPTIONS.map((o) => (
  o.value === 'unknown' ? { ...o, label: 'Роль не задана' } : o
));

interface ISpeakerCardProps {
  label: string;
  name: string;
  side: PublicSpeakerSide | '';
  role: FunctionalRole;
  canEdit: boolean;
  /** Роль сохраняется только для машинных меток и только при назначенной стороне. */
  roleEnabled: boolean;
  onSetName: (label: string, name: string) => void;
  onSetSide: (label: string, side: PublicSpeakerSide | '') => void;
  onSetRole: (label: string, role: FunctionalRole) => void;
}

/** Строка-карточка спикера: имя + метка, сторона, роль — без вложенных раскрывающихся блоков. */
export const SpeakerCard: FC<ISpeakerCardProps> = ({
  label, name, side, role, canEdit, roleEnabled, onSetName, onSetSide, onSetRole,
}) => (
  <div className={`${styles.card} ${side === '' ? styles.cardPending : ''}`}>
    <div className={styles.cardTop}>
      {canEdit ? (
        <SpeakerNameInput
          value={name}
          placeholder={label}
          inputClassName={styles.nameInput}
          onCommit={(v) => onSetName(label, v)}
        />
      ) : (
        <span className={styles.nameText} title={label}>{name || label}</span>
      )}
      <span className={styles.rawLabel} title="Метка распознавания">{label}</span>
    </div>
    <div className={styles.cardBottom}>
      <div className={styles.seg} role="group" aria-label={`Сторона: ${name || label}`}>
        {SIDE_CHOICES.map((c) => (
          <button
            key={c.label}
            type="button"
            disabled={!canEdit}
            aria-pressed={side === c.side}
            className={`${styles.segBtn}${side === c.side ? ` ${c.side === 'self' ? styles.segSelf : c.side === 'opponent' ? styles.segOpp : styles.segNone}` : ''}`}
            onClick={() => onSetSide(label, c.side)}
          >
            {c.label}
          </button>
        ))}
      </div>
      <Select
        value={role}
        onChange={(v) => onSetRole(label, v as FunctionalRole)}
        options={ROLE_SELECT_OPTIONS}
        disabled={!canEdit || !roleEnabled}
        ariaLabel={`Роль: ${name || label}`}
        className={styles.roleWrap}
        triggerClassName={styles.roleSelect}
      />
    </div>
  </div>
);
