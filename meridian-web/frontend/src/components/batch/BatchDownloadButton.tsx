import type { FC } from 'react';
import styles from './BatchDownloadButton.module.css';

interface IBatchDownloadButtonProps {
  label: string;
  onClick: () => void;
}

export const BatchDownloadButton: FC<IBatchDownloadButtonProps> = ({ label, onClick }) => (
  <button onClick={onClick} className={styles.btn}>
    {'⬇'} {label}
  </button>
);
