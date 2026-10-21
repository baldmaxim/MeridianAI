import type { FC } from 'react';
import styles from './SecondaryShadowPanel.module.css';

interface IShadowMetricProps {
  label: string;
  value: string;
  warn?: boolean;
}

export const ShadowMetric: FC<IShadowMetricProps> = ({ label, value, warn }) => (
  <div className={styles.metric}>
    <span className={styles.metricLabel}>{label}</span>
    <span className={`${styles.metricValue} ${warn ? styles.metricWarn : ''}`}>{value}</span>
  </div>
);
