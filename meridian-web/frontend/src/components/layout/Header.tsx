import { useState, useEffect } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import { RoleSwitch } from './RoleSwitch';
import { useOpenClose } from '../../hooks/useOpenClose';
import { IconSwap } from '../common/IconSwap';


interface Props {
  userName?: string;
  onLogout: () => void;
  onShowBatch?: () => void;
  showBatch?: boolean;
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
  inMeeting?: boolean;
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

export function Header({ userName, onLogout, onShowBatch, showBatch, onShowKnowledge, showKnowledge, onShowAISettings, showAISettings, onShowObjects, showObjects, onShowSettings, showSettings, canSwitchRole, viewAsUser, onToggleViewAs, inMeeting }: Props) {
  // Meeting-meta (название встречи, таймер, бейдж роли) показываем только на
  // странице встречи — вне неё «зависший» ярлык роли/имя встречи не нужен.
  const activeRoleName = useMeetingStore((s) => (inMeeting ? s.activeRoleName : null));
  const meetingName = useMeetingStore((s) => (inMeeting ? s.meetingName : ''));
  const [menuOpen, setMenuOpen] = useState(false);
  const menu = useOpenClose(menuOpen, { closeVar: '--dropdown-close-dur', fallbackMs: 150 });

  const navItems = ([
    onShowObjects && { label: 'Проекты', onClick: onShowObjects, active: showObjects },
    onShowKnowledge && { label: 'База знаний', onClick: onShowKnowledge, active: showKnowledge },
    onShowAISettings && { label: 'AI-профили', onClick: onShowAISettings, active: showAISettings },
    onShowBatch && { label: 'Оффлайн распознавание', onClick: onShowBatch, active: showBatch },
    onShowSettings && { label: '⚙ Настройки', onClick: onShowSettings, active: showSettings },
  ].filter(Boolean)) as { label: string; onClick: () => void; active?: boolean }[];

  const handleNav = (fn: () => void) => { setMenuOpen(false); fn(); };

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
          {inMeeting && <SessionTimer />}
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
          {navItems.map((it) => (
            <button
              key={it.label}
              className="header-desktop-btn"
              onClick={it.onClick}
              style={it.active ? styles.adminBtnActive : styles.adminBtn}
            >
              {it.label}
            </button>
          ))}
          {canSwitchRole && onToggleViewAs && (
            <span className="header-roleswitch">
              <RoleSwitch viewAsUser={!!viewAsUser} onToggle={onToggleViewAs} />
            </span>
          )}
          <button className="header-desktop-btn" onClick={onLogout} style={styles.logout}>
            Выход
          </button>
          <button
            className="header-burger"
            style={styles.burger}
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Меню"
          >
            <IconSwap state={menuOpen ? 'b' : 'a'} a="☰" b="✕" />
          </button>
        </div>
      </header>

      {menu.mounted && (
        <div className={`header-menu t-dropdown ${menu.cls}`.trim()} data-origin="top-right" style={styles.menu}>
          {navItems.map((it) => (
            <button
              key={it.label}
              onClick={() => handleNav(it.onClick)}
              style={it.active ? styles.menuItemActive : styles.menuItem}
            >
              {it.label}
            </button>
          ))}
          {canSwitchRole && onToggleViewAs && (
            <div style={styles.menuRole}>
              <RoleSwitch viewAsUser={!!viewAsUser} onToggle={onToggleViewAs} />
            </div>
          )}
          <button onClick={() => handleNav(onLogout)} style={styles.menuItem}>
            Выход
          </button>
        </div>
      )}
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
  burger: {
    display: 'none',
    alignItems: 'center',
    justifyContent: 'center',
    width: 34,
    height: 34,
    background: 'transparent',
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 6,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 16,
    lineHeight: 1,
    flexShrink: 0,
  },
  menu: {
    position: 'fixed',
    top: 44,
    left: 0,
    right: 0,
    zIndex: 200,
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    padding: 10,
    background: theme.bg.secondary,
    borderBottom: `1px solid ${theme.border.default}`,
    boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
  },
  menuItem: {
    width: '100%',
    textAlign: 'left' as const,
    padding: '11px 14px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 6,
    color: theme.text.primary,
    cursor: 'pointer',
    fontSize: 13,
    fontFamily: theme.font.mono,
    letterSpacing: '0.04em',
  },
  menuItemActive: {
    width: '100%',
    textAlign: 'left' as const,
    padding: '11px 14px',
    background: theme.accent.amberGlow,
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 6,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 13,
    fontFamily: theme.font.mono,
    letterSpacing: '0.04em',
  },
  menuRole: {
    display: 'flex',
    justifyContent: 'center',
    padding: '8px 0',
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
