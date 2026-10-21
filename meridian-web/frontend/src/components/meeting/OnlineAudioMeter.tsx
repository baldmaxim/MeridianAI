import type { FC } from 'react';
import styles from './OnlineAudioPanel.module.css';

interface IOnlineAudioMeterProps {
  label: string;
  value: number;
  /** Класс заливки полосы (цвет по токену темы) */
  fillClass: string;
}

export const OnlineAudioMeter: FC<IOnlineAudioMeterProps> = ({ label, value, fillClass }) => {
  // rms обычно сильно ниже 1 — растягиваем, чтобы полоса была читаемой.
  const level = Math.min(1, Math.max(0, value * 2.5));
  return (
    <div className={styles.meterRow}>
      <span className={styles.meterLabel}>{label}</span>
      <span className={styles.meterTrack}>
        <span className={`${styles.meterFill} ${fillClass}`} style={{ transform: `scaleX(${level})` }} />
      </span>
    </div>
  );
};
