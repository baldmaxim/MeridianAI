import { useState } from 'react';
import { AdminPage } from './AdminPage';
import { SettingsPage } from './SettingsPage';
import styles from './SettingsHubPage.module.css';
import { cx } from '../utils/cx';

interface Props {
  onBack: () => void;
}

const SECTIONS = [
  { id: 'admin', icon: '\u{1F6E0}', label: 'Админ-панель' },
  { id: 'settings', icon: '⚙', label: 'Настройки' },
] as const;

type Section = (typeof SECTIONS)[number]['id'];

export function SettingsHubPage({ onBack }: Props) {
  const [section, setSection] = useState<Section>('admin');

  return (
    <div className={styles.container}>
      <div className={styles.topBar}>
        <button onClick={onBack} className={styles.backBtn}>&larr; К переговорам</button>
        <span className={styles.topTitle}>НАСТРОЙКИ</span>
      </div>

      <div className={cx('settings-shell-layout mobile-content-pad', styles.layout)}>
        <nav className={styles.nav}>
          {SECTIONS.map((sec) => (
            <button
              key={sec.id}
              onClick={() => setSection(sec.id)}
              className={cx(section === sec.id ? styles.navActive : styles.navItem)}
            >
              <span className={styles.navIcon}>{sec.icon}</span> {sec.label}
            </button>
          ))}
        </nav>
        <div className={styles.content}>
          {section === 'admin' && <AdminPage embedded />}
          {section === 'settings' && <SettingsPage embedded />}
        </div>
      </div>
    </div>
  );
}
