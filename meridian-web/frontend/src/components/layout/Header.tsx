import { useState, useEffect } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import { RoleSwitch } from './RoleSwitch';


interface Props {
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

/* Inline SVG compass mark from branding/meridian-logos.html */
function LogoMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
      <circle cx="14" cy="14" r="12" stroke="#F5A623" strokeWidth="1" opacity="0.25"/>
      <circle cx="14" cy="14" r="7" stroke="#F5A623" strokeWidth="1.5" opacity="0.6"/>
      <circle cx="14" cy="14" r="2.5" fill="#F5A623"/>
      <line x1="14" y1="2" x2="14" y2="6" stroke="#F5A623" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="14" y1="22" x2="14" y2="26" stroke="#F5A623" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="2" y1="14" x2="6" y2="14" stroke="#F5A623" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="22" y1="14" x2="26" y2="14" stroke="#F5A623" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

function SessionTimer() {
  const isListening = useMeetingStore((s) => s.isListening);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!isListening) { setElapsed(0); return; }
    const start = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [isListening]);

  if (!isListening) return null;

  const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');

  return (
    <div className="header-session-group" style={styles.sessionGroup}>
      <span className="header-session-badge" style={styles.sessionBadge}>
        <span className="pulse-dot" style={styles.sessionDot} />
        <span className="header-session-text">СЕССИЯ АКТИВНА</span>
      </span>
      <span className="header-timer" style={styles.timer}>{h} : {m} : {s}</span>
      {/* Compact mobile badge: dot + mm:ss */}
      <span className="header-session-compact" style={styles.sessionCompact}>
        <span className="pulse-dot" style={styles.sessionDot} />
        {m}:{s}
      </span>
    </div>
  );
}

export function Header({ userName, userRole, onLogout, showAdmin, onToggleAdmin, onShowHistory, showHistory, onShowBatch, showBatch, onShowDirectory, showDirectory, onShowKnowledge, showKnowledge, onShowAISettings, showAISettings, onShowObjects, showObjects, onShowSettings, showSettings, canSwitchRole, viewAsUser, onToggleViewAs }: Props) {
  const activeRoleName = useMeetingStore((s) => s.activeRoleName);
  const meetingName = useMeetingStore((s) => s.meetingName);

  return (
    <>
      <header className="header-inner" style={styles.header}>
        <div
          className="header-logo"
          style={{ ...styles.logo, cursor: onShowObjects ? 'pointer' : 'default' }}
          onClick={onShowObjects}
          title={onShowObjects ? 'К объектам' : undefined}
        >
          <LogoMark />
          <div>
            <div className="header-logo-text" style={styles.logoText}>
              MERIDI<span style={{ color: theme.accent.amber }}>AN</span>
            </div>
          </div>
        </div>

        <div className="header-center" style={styles.center}>
          {meetingName && (
            <span className="header-meeting-name" style={styles.meetingName}>{meetingName}</span>
          )}
          <SessionTimer />
        </div>

        <div className="header-right" style={styles.right}>
          {activeRoleName && (
            <span className="header-role-badge" style={styles.roleBadge}>
              {activeRoleName}
            </span>
          )}
          {userName && (
            <div className="header-avatar" style={styles.avatar}>
              {(userName[0] || 'U').toUpperCase()}
            </div>
          )}
          {onShowObjects && (
            <button
              className="header-desktop-btn"
              onClick={onShowObjects}
              style={showObjects ? styles.adminBtnActive : styles.adminBtn}
            >
              Проекты
            </button>
          )}
          {onShowDirectory && (
            <button
              className="header-desktop-btn"
              onClick={onShowDirectory}
              style={showDirectory ? styles.adminBtnActive : styles.adminBtn}
            >
              Справочники
            </button>
          )}
          {onShowKnowledge && (
            <button
              className="header-desktop-btn"
              onClick={onShowKnowledge}
              style={showKnowledge ? styles.adminBtnActive : styles.adminBtn}
            >
              База знаний
            </button>
          )}
          {onShowAISettings && (
            <button
              className="header-desktop-btn"
              onClick={onShowAISettings}
              style={showAISettings ? styles.adminBtnActive : styles.adminBtn}
            >
              AI-профили
            </button>
          )}
          {onShowBatch && (
            <button
              className="header-desktop-btn"
              onClick={onShowBatch}
              style={showBatch ? styles.adminBtnActive : styles.adminBtn}
            >
              Протоколы
            </button>
          )}
          {onShowHistory && (
            <button
              className="header-desktop-btn"
              onClick={onShowHistory}
              style={showHistory ? styles.adminBtnActive : styles.adminBtn}
            >
              История
            </button>
          )}
          {onShowSettings && (
            <button
              className="header-desktop-btn"
              onClick={onShowSettings}
              style={showSettings ? styles.adminBtnActive : styles.adminBtn}
            >
              ⚙ Настройки
            </button>
          )}
          {userRole === 'admin' && onToggleAdmin && (
            <button
              className="header-desktop-btn"
              onClick={onToggleAdmin}
              style={showAdmin ? styles.adminBtnActive : styles.adminBtn}
            >
              Админ
            </button>
          )}
          {canSwitchRole && onToggleViewAs && (
            <RoleSwitch viewAsUser={!!viewAsUser} onToggle={onToggleViewAs} />
          )}
          <button className="header-desktop-btn" onClick={onLogout} style={styles.logout}>
            Выход
          </button>
        </div>
      </header>
      {(activeRoleName || meetingName) && (
        <div className="mobile-role-strip" style={styles.mobileRoleStrip}>
          {meetingName && (
            <>
              <span style={styles.mobileRoleDot} />
              <span style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{meetingName}</span>
            </>
          )}
          {activeRoleName && meetingName && <span style={{ opacity: 0.3, margin: '0 4px' }}>|</span>}
          {activeRoleName && (
            <>
              <span style={styles.mobileRoleDot} />
              {activeRoleName}
            </>
          )}
        </div>
      )}
    </>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 24px',
    height: 52,
    background: theme.bg.secondary,
    borderBottom: `1px solid ${theme.border.default}`,
    flexShrink: 0,
  },
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  logoText: {
    fontFamily: theme.font.heading,
    fontWeight: 800,
    fontSize: 15,
    letterSpacing: '0.18em',
    color: theme.text.primary,
  },
  logoSub: {
    fontFamily: theme.font.mono,
    fontSize: 9,
    color: theme.text.muted,
    letterSpacing: '0.12em',
    marginTop: -2,
  },
  center: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  meetingName: {
    fontFamily: theme.font.body,
    fontSize: 12,
    fontWeight: 500,
    color: theme.text.secondary,
    maxWidth: 220,
    overflow: 'hidden' as const,
    textOverflow: 'ellipsis' as const,
    whiteSpace: 'nowrap' as const,
  },
  sessionGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  sessionBadge: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '4px 12px',
    background: 'rgba(46,229,157,0.1)',
    border: '1px solid rgba(46,229,157,0.25)',
    borderRadius: 20,
    fontSize: 9,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.1em',
    color: theme.accent.green,
    textTransform: 'uppercase' as const,
  },
  sessionDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent.green,
  },
  timer: {
    fontFamily: theme.font.mono,
    fontSize: 13,
    color: theme.text.secondary,
    letterSpacing: '0.08em',
  },
  sessionCompact: {
    display: 'none',
    alignItems: 'center',
    gap: 5,
    padding: '4px 9px',
    background: 'rgba(46,229,157,0.1)',
    border: '1px solid rgba(46,229,157,0.2)',
    borderRadius: 20,
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.accent.green,
    letterSpacing: '0.06em',
    fontWeight: 600,
  },
  right: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  avatar: {
    width: 26,
    height: 26,
    borderRadius: '50%',
    background: theme.bg.elevated,
    border: `1px solid ${theme.border.amber}`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 10,
    color: theme.accent.amber,
    fontFamily: theme.font.heading,
    fontWeight: 700,
  },
  adminBtn: {
    padding: '4px 12px',
    background: 'transparent',
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 5,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.08em',
  },
  adminBtnActive: {
    padding: '4px 12px',
    background: theme.accent.amberGlow,
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 5,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.08em',
  },
  logout: {
    padding: '4px 10px',
    background: 'transparent',
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 4,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    letterSpacing: '0.08em',
  },
  roleBadge: {
    padding: '3px 10px',
    fontSize: 9,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.06em',
    color: theme.accent.amber,
    border: '1px solid rgba(245,166,35,0.25)',
    borderRadius: 12,
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden' as const,
    textOverflow: 'ellipsis' as const,
    maxWidth: 140,
  },
  mobileRoleStrip: {
    display: 'none',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    padding: '4px 14px',
    background: theme.bg.secondary,
    borderBottom: `1px solid ${theme.border.default}`,
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    color: theme.accent.amber,
    letterSpacing: '0.06em',
    flexShrink: 0,
  },
  mobileRoleDot: {
    width: 5,
    height: 5,
    borderRadius: '50%',
    background: theme.accent.amber,
    flexShrink: 0,
  },
};
