import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import styles from './StatusBar.module.css';

export const StatusBar: FC = () => {
  const status = useMeetingStore((s) => s.statusMessage);
  const isConnected = useMeetingStore((s) => s.isConnected);
  const lastError = useMeetingStore((s) => s.lastError);

  return (
    <div className={styles.bar}>
      <span className={`pulse-dot ${styles.dot} ${isConnected ? styles.dotConnected : ''}`} />
      <span className={styles.text}>{lastError || status}</span>
    </div>
  );
};
