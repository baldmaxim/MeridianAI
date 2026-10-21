import type { ReactNode } from 'react';
import { Header } from './Header';
import styles from './AppLayout.module.css';

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
  onShowFiles?: () => void;
  showFiles?: boolean;
  onShowDesktop?: () => void;
  showDesktop?: boolean;
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
  inObjectDetail?: boolean;
}

export function AppLayout({ children, userName, onLogout, onShowBatch, showBatch, onShowKnowledge, showKnowledge, onShowLetters, showLetters, onShowFiles, showFiles, onShowDesktop, showDesktop, onShowAISettings, showAISettings, onShowObjects, showObjects, onShowSettings, showSettings, canSwitchRole, viewAsUser, onToggleViewAs, inMeeting, inObjectDetail }: Props) {
  return (
    <div className={styles.container}>
      <Header userName={userName} onLogout={onLogout} onShowBatch={onShowBatch} showBatch={showBatch} onShowKnowledge={onShowKnowledge} showKnowledge={showKnowledge} onShowLetters={onShowLetters} showLetters={showLetters} onShowFiles={onShowFiles} showFiles={showFiles} onShowDesktop={onShowDesktop} showDesktop={showDesktop} onShowAISettings={onShowAISettings} showAISettings={showAISettings} onShowObjects={onShowObjects} showObjects={showObjects} onShowSettings={onShowSettings} showSettings={showSettings} canSwitchRole={canSwitchRole} viewAsUser={viewAsUser} onToggleViewAs={onToggleViewAs} inMeeting={inMeeting} inObjectDetail={inObjectDetail} />
      <main className={styles.main}>{children}</main>
    </div>
  );
}
