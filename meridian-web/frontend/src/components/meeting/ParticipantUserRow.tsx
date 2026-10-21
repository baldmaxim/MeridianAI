import type { FC } from 'react';
import type { ParticipantUser } from '../../lib/participants';
import styles from './ParticipantsBadge.module.css';

interface IParticipantUserRowProps {
  user: ParticipantUser;
}

export const ParticipantUserRow: FC<IParticipantUserRowProps> = ({ user }) => {
  const devices = user.deviceLabels.join(', ');
  return (
    <div className={styles.row}>
      <div className={styles.rowMain}>
        <span className={styles.name}>{user.label}</span>
        <span className={styles.devices}>{devices}</span>
      </div>
      <div className={styles.tags}>
        {user.isRecording && <span className={`${styles.tag} ${styles.tagRec}`}>пишет звук</span>}
        {user.isHelper && <span className={`${styles.tag} ${styles.tagHelp}`}>помогает</span>}
        {!user.isRecording && !user.isHelper && (
          <span className={`${styles.tag} ${styles.tagIdle}`}>наблюдает</span>
        )}
      </div>
    </div>
  );
};
