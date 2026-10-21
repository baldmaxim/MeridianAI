import type { FC } from 'react';
import type { EvidenceRef } from '../../types';
import styles from './ProtocolEvidence.module.css';

interface IProtocolEvidenceProps {
  ev: EvidenceRef[];
}

/** Цитаты-подтверждения пункта протокола (таймкод, спикер, фраза). */
export const ProtocolEvidence: FC<IProtocolEvidenceProps> = ({ ev }) => {
  if (!ev || ev.length === 0) return null;
  return (
    <div className={styles.evidence}>
      {ev.map((e, i) => (
        <span key={i} className={styles.evItem}>
          {e.timecode ? `[${e.timecode}] ` : ''}{e.speaker ? `${e.speaker}: ` : ''}«{e.quote}»
        </span>
      ))}
    </div>
  );
};
