import type { ReactNode } from 'react';
import { theme } from '../../styles/theme';
import { Header } from './Header';

interface Props {
  children: ReactNode;
  userName?: string;
  userRole?: string;
  onLogout: () => void;
  showAdmin?: boolean;
  onToggleAdmin?: () => void;
  onShowHistory?: () => void;
  showHistory?: boolean;
  onShowBatch?: () => void;
  showBatch?: boolean;
}

export function AppLayout({ children, userName, userRole, onLogout, showAdmin, onToggleAdmin, onShowHistory, showHistory, onShowBatch, showBatch }: Props) {
  return (
    <div style={styles.container}>
      <Header userName={userName} userRole={userRole} onLogout={onLogout} showAdmin={showAdmin} onToggleAdmin={onToggleAdmin} onShowHistory={onShowHistory} showHistory={showHistory} onShowBatch={onShowBatch} showBatch={showBatch} />
      <main style={styles.main}>{children}</main>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    background: theme.bg.primary,
    color: theme.text.primary,
    fontFamily: theme.font.body,
  },
  main: {
    flex: 1,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
};
