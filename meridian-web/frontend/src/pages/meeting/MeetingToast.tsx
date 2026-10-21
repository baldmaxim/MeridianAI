import type { FC } from 'react';
import styles from './MeetingToast.module.css';

export interface IMeetingToastData {
  message: string;
  type: 'success' | 'error';
}

interface IMeetingToastProps {
  toast: IMeetingToastData;
}

export const MeetingToast: FC<IMeetingToastProps> = ({ toast }) => {
  const variant = toast.type === 'success' ? styles.success : styles.error;
  return (
    <div className={`${styles.toast} ${variant}`}>
      <span className={styles.dot} />
      <span className={styles.text}>{toast.message}</span>
    </div>
  );
};
