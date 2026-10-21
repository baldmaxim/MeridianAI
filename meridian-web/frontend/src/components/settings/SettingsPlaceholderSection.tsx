import type { FC } from 'react';
import styles from './SettingsPlaceholderSection.module.css';

interface ISettingsPlaceholderSectionProps {
  title: string;
  text: string;
}

/** Заглушка раздела настроек, который ещё в разработке. */
export const SettingsPlaceholderSection: FC<ISettingsPlaceholderSectionProps> = ({ title, text }) => (
  <div className={styles.placeholderCard}>
    <div className={styles.sectionHeader}>
      <span className={styles.dot} />
      <span className={styles.sectionTitle}>{title}</span>
    </div>
    <div className={styles.placeholderText}>{text}</div>
  </div>
);
