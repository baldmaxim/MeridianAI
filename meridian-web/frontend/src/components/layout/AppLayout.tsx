import type { ReactNode } from 'react';
import { theme } from '../../styles/theme';
import { Header } from './Header';
import { AppUpdateBanner } from '../AppUpdateBanner';
import { useAppUpdate } from '../../hooks/useAppUpdate';

interface Props {
  children: ReactNode;
  userName?: string;
  onLogout: () => void;
  onShowBatch?: () => void;
  showBatch?: boolean;
  onShowKnowledge?: () => void;
  showKnowledge?: boolean;
  onShowLetters?: () => void;
  showLetters?: boolean;
  onShowAISettings?: () => void;
  showAISettings?: boolean;
  onShowObjects?: () => void;
  showObjects?: boolean;
  onShowSettings?: () => void;
  showSettings?: boolean;
  canSwitchRole?: boolean;
  viewAsUser?: boolean;
  onToggleViewAs?: () => void;
  inMeeting?: boolean;
}

export function AppLayout({ children, userName, onLogout, onShowBatch, showBatch, onShowKnowledge, showKnowledge, onShowLetters, showLetters, onShowAISettings, showAISettings, onShowObjects, showObjects, onShowSettings, showSettings, canSwitchRole, viewAsUser, onToggleViewAs, inMeeting }: Props) {
  const updateAvailable = useAppUpdate();
  return (
    <div style={styles.container}>
      <Header userName={userName} onLogout={onLogout} onShowBatch={onShowBatch} showBatch={showBatch} onShowKnowledge={onShowKnowledge} showKnowledge={showKnowledge} onShowLetters={onShowLetters} showLetters={showLetters} onShowAISettings={onShowAISettings} showAISettings={showAISettings} onShowObjects={onShowObjects} showObjects={showObjects} onShowSettings={onShowSettings} showSettings={showSettings} canSwitchRole={canSwitchRole} viewAsUser={viewAsUser} onToggleViewAs={onToggleViewAs} inMeeting={inMeeting} />
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
