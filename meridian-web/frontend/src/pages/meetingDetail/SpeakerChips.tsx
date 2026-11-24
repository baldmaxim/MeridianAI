import type { FC } from 'react';
import { toPublicSpeakerSide } from '../../lib/speakerSides';
import type { SpeakerRoleOut } from '../../types';
import { cx } from '../../utils/cx';
import { humanSpeakerLabel } from './speakerList';
import type { IMeetingSpeaker } from './speakerList';
import styles from './SpeakerChips.module.css';

interface ISpeakerChipsProps {
  speakers: IMeetingSpeaker[];
  roleByLabel: Map<string, SpeakerRoleOut>;
  /** Клик по чипу — раскрыть редактор спикеров. */
  onClick: () => void;
}

const SIDE_TAG = { self: 'Мы', opponent: 'Оппонент' } as const;

/** Чипы спикеров: имя (или «Спикер N»), сторона («Мы» / «Оппонент» / «?»), число реплик. */
export const SpeakerChips: FC<ISpeakerChipsProps> = ({ speakers, roleByLabel, onClick }) => (
  <>
    {speakers.map((s) => {
      const role = roleByLabel.get(s.label);
      const side = toPublicSpeakerSide(role?.side);
      const name = role?.display_name || humanSpeakerLabel(s.label);
      return (
        <button key={s.label} type="button" className={styles.chip} onClick={onClick} title={name}>
          <span className={styles.name}>{name}</span>
          <span className={cx(styles.tag, side === 'self' && styles.tagSelf, side === 'opponent' && styles.tagOpp, !side && styles.tagNone)}>
            {side ? SIDE_TAG[side] : '?'}
          </span>
          <span className={styles.count}>{s.count}</span>
        </button>
      );
    })}
  </>
);
