import { useState } from 'react';
import { AdminPage } from './AdminPage';
import { SettingsPage } from './SettingsPage';
import { AISettingsPage } from './AISettingsPage';
import styles from './SettingsHubPage.module.css';
import { cx } from '../utils/cx';

interface Props {
  onBack: () => void;
  /** Администрирование видит только админ не в режиме «как пользователь» */
  isAdmin: boolean;
}

const SECTIONS = [
  { id: 'settings', icon: '⚙', label: 'Настройки' },
  { id: 'ai-profiles', icon: '\u{1F916}', label: 'AI-профили' },
  { id: 'admin', icon: '\u{1F6E0}', label: 'Администрирование' },
] as const;

type Section = (typeof SECTIONS)[number]['id'];

export function SettingsHubPage({ onBack, isAdmin }: Props) {
  const [section, setSection] = useState<Section>('settings');
  const sections = SECTIONS.filter((sec) => sec.id !== 'admin' || isAdmin);
  // Если админ переключился в режим «как пользователь» на открытой секции — показываем настройки
  const activeSection: Section = sections.some((sec) => sec.id === section) ? section : 'settings';

  return (
    <div className={styles.container}>
      <div className={styles.topBar}>
        <button onClick={onBack} className={styles.backBtn}>&larr; К переговорам</button>
        <span className={styles.topTitle}>НАСТРОЙКИ</span>
      </div>

      <div className={cx('settings-shell-layout mobile-content-pad', styles.layout)}>
        <nav className={styles.nav}>
          {sections.map((sec) => (
            <button
              key={sec.id}
              onClick={() => setSection(sec.id)}
              className={cx(activeSection === sec.id ? styles.navActive : styles.navItem)}
            >
              <span className={styles.navIcon}>{sec.icon}</span> {sec.label}
            </button>
          ))}
        </nav>
        <div className={styles.content}>
          {activeSection === 'settings' && <SettingsPage embedded />}
          {activeSection === 'ai-profiles' && <AISettingsPage embedded />}
          {activeSection === 'admin' && isAdmin && <AdminPage embedded />}
        </div>
      </div>
    </div>
  );
}
