import { useState } from 'react';
import { theme } from '../styles/theme';
import { AdminPage } from './AdminPage';
import { SettingsPage } from './SettingsPage';

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
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button onClick={onBack} style={styles.backBtn}>&larr; К переговорам</button>
        <span style={styles.topTitle}>НАСТРОЙКИ</span>
      </div>

      <div className="settings-shell-layout mobile-content-pad" style={styles.layout}>
        <nav style={styles.nav}>
          {SECTIONS.map((sec) => (
            <button
              key={sec.id}
              onClick={() => setSection(sec.id)}
              style={section === sec.id ? styles.navActive : styles.navItem}
            >
              <span style={{ fontSize: 14 }}>{sec.icon}</span> {sec.label}
            </button>
          ))}
        </nav>
        <div style={styles.content}>
          {section === 'admin' && <AdminPage embedded />}
          {section === 'settings' && <SettingsPage embedded />}
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'auto', padding: '20px 24px' },
  topBar: {
    display: 'flex', alignItems: 'center', gap: 16,
    paddingBottom: 12, marginBottom: 20,
    borderBottom: `1px solid ${theme.border.default}`, flexShrink: 0,
  },
  backBtn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 16px',
    background: 'transparent', border: `1px solid ${theme.accent.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em', flexShrink: 0,
  },
  topTitle: {
    fontFamily: theme.font.mono, fontSize: 11, fontWeight: 500,
    letterSpacing: '0.16em', color: theme.text.secondary, flex: 1,
  },
  layout: { display: 'flex', gap: 24, alignItems: 'flex-start' },
  nav: { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 200, flexShrink: 0 },
  navActive: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: theme.accent.amber, color: '#080A0F', border: 'none', borderRadius: 8,
    fontSize: 12, fontWeight: 600, fontFamily: theme.font.body, cursor: 'pointer', textAlign: 'left' as const,
  },
  navItem: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: 'transparent', color: theme.text.secondary, border: `1px solid ${theme.border.default}`,
    borderRadius: 8, fontSize: 12, fontFamily: theme.font.body, cursor: 'pointer', textAlign: 'left' as const,
  },
  content: { flex: 1, minWidth: 0 },
};
