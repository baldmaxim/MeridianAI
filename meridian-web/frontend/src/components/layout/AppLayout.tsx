import type { ReactNode } from 'react';
import { theme } from '../../styles/theme';
import { Header } from './Header';
import { AppUpdateBanner } from '../AppUpdateBanner';
import { useAppUpdate } from '../../hooks/useAppUpdate';

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
  onShowDirectory?: () => void;
  showDirectory?: boolean;
  onShowKnowledge?: () => void;
  showKnowledge?: boolean;
  onShowAISettings?: () => void;
  showAISettings?: boolean;
  onShowObjects?: () => void;
  showObjects?: boolean;
  onShowSettings?: () => void;
  showSettings?: boolean;
  canSwitchRole?: boolean;
  viewAsUser?: boolean;
  onToggleViewAs?: () => void;
}

export function AppLayout({ children, userName, userRole, onLogout, showAdmin, onToggleAdmin, onShowHistory, showHistory, onShowBatch, showBatch, onShowDirectory, showDirectory, onShowKnowledge, showKnowledge, onShowAISettings, showAISettings, onShowObjects, showObjects, onShowSettings, showSettings, canSwitchRole, viewAsUser, onToggleViewAs }: Props) {
  const updateAvailable = useAppUpdate();
  return (
    <div style={styles.container}>
      <Header userName={userName} userRole={userRole} onLogout={onLogout} showAdmin={showAdmin} onToggleAdmin={onToggleAdmin} onShowHistory={onShowHistory} showHistory={showHistory} onShowBatch={onShowBatch} showBatch={showBatch} onShowDirectory={onShowDirectory} showDirectory={showDirectory} onShowKnowledge={onShowKnowledge} showKnowledge={showKnowledge} onShowAISettings={onShowAISettings} showAISettings={showAISettings} onShowObjects={onShowObjects} showObjects={showObjects} onShowSettings={onShowSettings} showSettings={showSettings} canSwitchRole={canSwitchRole} viewAsUser={viewAsUser} onToggleViewAs={onToggleViewAs} />
      <AppUpdateBanner updateAvailable={updateAvailable} />
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
