import { useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { paths, navTo } from '../../lib/navigation';
import { logoutAll } from '../../api/auth';
import { LogoMark } from './LogoMark';
import { SessionTimer } from './SessionTimer';
import { IconSwap } from '../common/IconSwap';
import { Icon } from '../common/Icon';
import { HeaderNav } from './HeaderNav';
import { HeaderMobileMenu } from './HeaderMobileMenu';
import { UserMenu } from './UserMenu';
import type { IHeaderNavModel } from './headerNav';
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

  // Шестерёнка «Настройки»: хаб настроек, а если его нет — AI-профили
  const settingsAction = onShowSettings
    ? { path: paths.settings, onClick: onShowSettings }
    : onShowAISettings
      ? { path: paths.aiSettings, onClick: onShowAISettings }
      : undefined;

  const nav: IHeaderNavModel = {
    objects: onShowObjects && { path: paths.objects, onClick: onShowObjects, active: !!showObjects },
    letters: onShowLetters && { path: paths.letters, onClick: onShowLetters, active: !!showLetters },
    knowledge: onShowKnowledge && { path: paths.knowledge, onClick: onShowKnowledge, active: !!showKnowledge },
    files: onShowFiles && { path: paths.files, onClick: onShowFiles, active: !!showFiles },
    batch: onShowBatch && { path: paths.batch, onClick: onShowBatch, active: !!showBatch },
    desktop: onShowDesktop && { path: paths.desktop, onClick: onShowDesktop, active: !!showDesktop },
    settings: settingsAction && { ...settingsAction, active: !!showSettings || !!showAISettings },
  };

  // Завершает все сессии пользователя на сервере, затем обычный локальный выход
  const handleLogoutAll = async () => {
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

        {/* На встрече ряд табов не показываем — чтобы не уйти со встречи случайным кликом */}
        {!inMeeting && <HeaderNav nav={nav} />}

        <div className={`header-right ${styles.right}`}>
          {activeRoleName && (
            <span className={`header-role-badge ${styles.roleBadge}`}>
              {activeRoleName}
            </span>
          )}
          {settingsAction && (
            <button
              type="button"
              className={`t-btn ${styles.iconBtn} ${nav.settings?.active ? styles.iconBtnActive : ''}`}
              aria-label="Настройки"
              title="Настройки"
              {...navTo(settingsAction.path, settingsAction.onClick)}
            >
              <Icon name="gear" size={20} />
            </button>
          )}
          {userName && (
            <UserMenu
              userName={userName}
              onLogout={onLogout}
              onLogoutAll={handleLogoutAll}
              canSwitchRole={canSwitchRole}
              viewAsUser={viewAsUser}
              onToggleViewAs={onToggleViewAs}
            />
          )}
          <button
            type="button"
            className={`t-btn ${styles.burger} ${inMeeting ? styles.burgerAlways : ''}`}
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Меню"
            aria-expanded={menuOpen}
          >
            <IconSwap state={menuOpen ? 'b' : 'a'} a={<Icon name="menu" />} b={<Icon name="close" />} />
          </button>
        </div>
      </header>

      <HeaderMobileMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        nav={nav}
        userName={userName}
        onLogout={onLogout}
        onLogoutAll={handleLogoutAll}
        canSwitchRole={canSwitchRole}
        viewAsUser={viewAsUser}
        onToggleViewAs={onToggleViewAs}
      />
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
