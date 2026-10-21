import type { ReactNode } from 'react';
import { ThemeToggle } from '../common/ThemeToggle';
import styles from './MobileLayout.module.css';

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
    <div className={styles.root}>
      <header className={styles.header}>
        {onBack ? (
          <button onClick={onBack} className={styles.backBtn} aria-label="Назад">‹</button>
        ) : (
          <span className={styles.brand}>MERIDI<span className={styles.brandAccent}>AN</span></span>
        )}
        <span className={styles.title}>{title}</span>
        <ThemeToggle />
        {onLogout ? (
          <button onClick={onLogout} className={styles.logout}>{userName ? '⎋' : 'Выход'}</button>
        ) : <span className={styles.headerSpacer} />}
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
