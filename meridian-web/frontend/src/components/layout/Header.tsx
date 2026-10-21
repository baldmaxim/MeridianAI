import { useCallback, useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { paths, navTo } from '../../lib/navigation';
import { logoutAll } from '../../api/auth';
import { RoleSwitch } from './RoleSwitch';
import { LogoMark } from './LogoMark';
import { SessionTimer } from './SessionTimer';
import { useOpenClose } from '../../hooks/useOpenClose';
import { IconSwap } from '../common/IconSwap';
import { ThemeToggle } from '../common/ThemeToggle';
import { Dropdown } from '../common/Dropdown';
import styles from './Header.module.css';

interface IHeaderProps {
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

export const Header: FC<IHeaderProps> = ({ userName, onLogout, onShowBatch, showBatch, onShowKnowledge, showKnowledge, onShowLetters, showLetters, onShowFiles, showFiles, onShowDesktop, showDesktop, onShowAISettings, showAISettings, onShowObjects, showObjects, onShowSettings, showSettings, canSwitchRole, viewAsUser, onToggleViewAs, inMeeting, inObjectDetail }) => {
  // Meeting-meta (название встречи, таймер, бейдж роли) показываем только на
  // странице встречи — вне неё «зависший» ярлык роли/имя встречи не нужен.
  const activeRoleName = useMeetingStore((s) => (inMeeting ? s.activeRoleName : null));
  const meetingName = useMeetingStore((s) => (inMeeting ? s.meetingName : ''));
  // Ярлык «Заказчик | Объект» — только на странице объекта.
  const objectHeader = useMeetingStore((s) => (inObjectDetail ? s.objectHeader : null));
  const showObjectTag = !!objectHeader && !!(objectHeader.customer || objectHeader.object);
  const [menuOpen, setMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const closeUserMenu = useCallback(() => setUserMenuOpen(false), []);
  const menu = useOpenClose(menuOpen, { closeVar: '--dropdown-close-dur', fallbackMs: 150 });

  const navItems = ([
    onShowObjects && { label: 'Проекты', path: paths.objects, onClick: onShowObjects, active: showObjects },
    onShowLetters && { label: 'Письма', path: paths.letters, onClick: onShowLetters, active: showLetters },
    onShowFiles && { label: 'Файлы', path: paths.files, onClick: onShowFiles, active: showFiles },
    onShowDesktop && { label: 'Приложение для ПК', path: paths.desktop, onClick: onShowDesktop, active: showDesktop },
    onShowKnowledge && { label: 'База знаний', path: paths.knowledge, onClick: onShowKnowledge, active: showKnowledge },
    onShowAISettings && { label: 'AI-профили', path: paths.aiSettings, onClick: onShowAISettings, active: showAISettings },
    onShowBatch && { label: 'Оффлайн распознавание', path: paths.batch, onClick: onShowBatch, active: showBatch },
    onShowSettings && { label: '⚙ Настройки', path: paths.settings, onClick: onShowSettings, active: showSettings },
  ].filter(Boolean)) as { label: string; path: string; onClick: () => void; active?: boolean }[];

  const handleNav = (fn: () => void) => { setMenuOpen(false); fn(); };

  // Завершает все сессии пользователя на сервере, затем обычный локальный выход
  const handleLogoutAll = async () => {
    setMenuOpen(false);
    setUserMenuOpen(false);
    if (!window.confirm('Выйти на всех устройствах? Все активные сессии будут завершены.')) return;
    try {
      await logoutAll();
    } catch {
      window.alert('Не удалось выйти на всех устройствах. Попробуйте ещё раз.');
      return;
    }
    onLogout();
  };

  return (
    <>
      <header className={`header-inner ${styles.header}`}>
        <div
          className={`header-logo ${styles.logo} ${onShowObjects ? styles.logoClickable : ''}`}
          {...(onShowObjects ? navTo(paths.objects, onShowObjects) : {})}
          title={onShowObjects ? 'К объектам' : undefined}
        >
          <LogoMark />
          <div>
            <div className={`header-logo-text ${styles.logoText}`}>
              MERIDI<span className={styles.logoAccent}>AN</span>
            </div>
          </div>
        </div>

        {meetingName && (
          <>
            <span className={`header-meeting-sep ${styles.meetingSep}`} aria-hidden="true" />
            <span className={`header-meeting-name ${styles.meetingName}`}>{meetingName}</span>
          </>
        )}
        {showObjectTag && (
          <>
            <span className={`header-object-sep ${styles.meetingSep}`} aria-hidden="true" />
            <span className={`header-object-tag ${styles.objectTag}`}>
              {objectHeader!.customer && (
                <span className={styles.objectTagCustomer}>{objectHeader!.customer}</span>
              )}
              {objectHeader!.customer && objectHeader!.object && (
                <span className={styles.objectTagSep} aria-hidden="true">|</span>
              )}
              {objectHeader!.object && (
                <span className={styles.objectTagObject}>{objectHeader!.object}</span>
              )}
            </span>
          </>
        )}
        {inMeeting && (
          <div className={`header-center ${styles.center}`}>
            <SessionTimer />
          </div>
        )}

        <div className={`header-right ${styles.right}`}>
          {activeRoleName && (
            <span className={`header-role-badge ${styles.roleBadge}`}>
              {activeRoleName}
            </span>
          )}
          {userName && (
            <div className={`header-avatar ${styles.userMenuWrap}`}>
              <button
                type="button"
                className={styles.avatar}
                aria-label="Меню пользователя"
                aria-haspopup="menu"
                aria-expanded={userMenuOpen}
                title={userName}
                // mousedown вне меню закрывает Dropdown — не даём ему сработать на самом триггере
                onMouseDown={(e) => e.nativeEvent.stopPropagation()}
                onClick={() => setUserMenuOpen((o) => !o)}
              >
                {(userName[0] || 'U').toUpperCase()}
              </button>
              <Dropdown open={userMenuOpen} onClose={closeUserMenu} origin="top-right" className={styles.userMenu}>
                <div className={styles.userMenuName}>{userName}</div>
                <button type="button" className={`t-btn ${styles.userMenuItem}`} onClick={handleLogoutAll}>
                  Выйти на всех устройствах
                </button>
              </Dropdown>
            </div>
          )}
          {navItems.map((it) => (
            <button
              key={it.label}
              className={`header-desktop-btn t-btn ${styles.adminBtn} ${it.active ? styles.adminBtnActive : ''}`}
              {...navTo(it.path, it.onClick)}
            >
              {it.label}
            </button>
          ))}
          {canSwitchRole && onToggleViewAs && (
            <span className="header-roleswitch">
              <RoleSwitch viewAsUser={!!viewAsUser} onToggle={onToggleViewAs} />
            </span>
          )}
          <ThemeToggle />
          <button className={`header-desktop-btn t-btn ${styles.logout}`} onClick={onLogout}>
            Выход
          </button>
          <button
            className={`header-burger t-btn ${styles.burger}`}
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Меню"
          >
            <IconSwap state={menuOpen ? 'b' : 'a'} a="☰" b="✕" />
          </button>
        </div>
      </header>

      {menu.mounted && (
        <div className={`header-menu t-dropdown ${menu.cls} ${styles.menu}`.trim()} data-origin="top-right">
          {navItems.map((it) => (
            <button
              key={it.label}
              {...navTo(it.path, () => handleNav(it.onClick))}
              className={`t-btn ${styles.menuItem} ${it.active ? styles.menuItemActive : ''}`}
            >
              {it.label}
            </button>
          ))}
          {canSwitchRole && onToggleViewAs && (
            <div className={styles.menuRole}>
              <RoleSwitch viewAsUser={!!viewAsUser} onToggle={onToggleViewAs} />
            </div>
          )}
          <button onClick={() => handleNav(onLogout)} className={`t-btn ${styles.menuItem}`}>
            Выход
          </button>
          <button onClick={handleLogoutAll} className={`t-btn ${styles.menuItem}`}>
            Выйти на всех устройствах
          </button>
        </div>
      )}
      {(activeRoleName || meetingName || showObjectTag) && (
        <div className={`mobile-role-strip ${styles.mobileRoleStrip}`}>
          {showObjectTag && (
            <>
              <span className={styles.mobileRoleDot} />
              <span className={`${styles.mobileRoleText} ${styles.mobileRoleObject}`}>
                {[objectHeader!.customer, objectHeader!.object].filter(Boolean).join(' | ')}
              </span>
            </>
          )}
          {meetingName && (
            <>
              <span className={styles.mobileRoleDot} />
              <span className={`${styles.mobileRoleText} ${styles.mobileRoleMeeting}`}>{meetingName}</span>
            </>
          )}
          {activeRoleName && meetingName && <span className={styles.mobileRoleSep}>|</span>}
          {activeRoleName && (
            <>
              <span className={styles.mobileRoleDot} />
              {activeRoleName}
            </>
          )}
        </div>
      )}
    </>
  );
};
