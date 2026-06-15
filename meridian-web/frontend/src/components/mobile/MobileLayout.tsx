import type { ReactNode } from 'react';
import { theme } from '../../styles/theme';

interface Props {
  children: ReactNode;
  title: string;
  userName?: string;
  onLogout?: () => void;
  onBack?: () => void;
}

/** Простой mobile-first каркас (верхняя панель + прокручиваемый контент). */
export function MobileLayout({ children, title, userName, onLogout, onBack }: Props) {
  return (
    <div style={styles.root}>
      <header style={styles.header}>
        {onBack ? (
          <button onClick={onBack} style={styles.backBtn} aria-label="Назад">‹</button>
        ) : (
          <span style={styles.brand}>MERIDI<span style={{ color: theme.accent.amber }}>AN</span></span>
        )}
        <span style={styles.title}>{title}</span>
        {onLogout ? (
          <button onClick={onLogout} style={styles.logout}>{userName ? '⎋' : 'Выход'}</button>
        ) : <span style={{ width: 28 }} />}
      </header>
      <main style={styles.main}>{children}</main>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex', flexDirection: 'column', height: '100vh',
    background: theme.bg.primary, color: theme.text.primary, fontFamily: theme.font.body,
  },
  header: {
    display: 'flex', alignItems: 'center', gap: 10, height: 52, flexShrink: 0,
    padding: '0 14px', background: theme.bg.secondary,
    borderBottom: `1px solid ${theme.border.default}`,
  },
  brand: {
    fontFamily: theme.font.heading, fontWeight: 800, fontSize: 14,
    letterSpacing: '0.14em', color: theme.text.primary, width: 90,
  },
  backBtn: {
    width: 28, height: 28, fontSize: 22, lineHeight: 1, background: 'transparent',
    border: 'none', color: theme.accent.amber, cursor: 'pointer',
  },
  title: {
    flex: 1, textAlign: 'center' as const, fontFamily: theme.font.mono, fontSize: 12,
    letterSpacing: '0.1em', color: theme.text.secondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  logout: {
    width: 28, minWidth: 28, height: 28, background: 'transparent',
    border: `1px solid ${theme.border.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 13, padding: 0,
  },
  main: {
    flex: 1, overflow: 'auto', padding: '14px 14px 28px',
    maxWidth: 600, width: '100%', margin: '0 auto', boxSizing: 'border-box' as const,
  },
};
