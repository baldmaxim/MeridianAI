import { useCallback, useState } from 'react';
import type { FC } from 'react';
import { Dropdown } from '../common/Dropdown';
import { NotificationBadge } from '../common/NotificationBadge';
import { Icon } from '../common/Icon';
import { RoleSwitch } from './RoleSwitch';
import { ThemeSegment } from './ThemeSegment';
import styles from './UserMenu.module.css';

interface IUserMenuProps {
  userName: string;
  onLogout: () => void;
  onLogoutAll: () => void;
  canSwitchRole?: boolean;
  viewAsUser?: boolean;
  onToggleViewAs?: () => void;
}

/** Аватар с выпадающим меню: имя, тема, переключатель роли, выход. */
export const UserMenu: FC<IUserMenuProps> = ({ userName, onLogout, onLogoutAll, canSwitchRole, viewAsUser, onToggleViewAs }) => {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  return (
    <div className={`header-avatar ${styles.wrap}`}>
      <button
        type="button"
        className={styles.avatar}
        aria-label="Меню пользователя"
        aria-haspopup="menu"
        aria-expanded={open}
        title={userName}
        // mousedown вне меню закрывает Dropdown — не даём ему сработать на самом триггере
        onMouseDown={(e) => e.nativeEvent.stopPropagation()}
        onClick={() => setOpen((o) => !o)}
      >
        {(userName[0] || 'U').toUpperCase()}
        {/* Админ в режиме «как пользователь» — точка на аватаре, чтобы не забыть про режим */}
        <NotificationBadge show={!!viewAsUser} className={styles.badge}>
          <span className={styles.badgeDot} />
        </NotificationBadge>
      </button>
      <Dropdown open={open} onClose={close} origin="top-right" className={styles.menu}>
        <div className={styles.name}>{userName}</div>
        <div className={styles.section}>
          <div className={styles.kicker}>Тема</div>
          <ThemeSegment />
        </div>
        {canSwitchRole && onToggleViewAs && (
          <div className={styles.role}>
            <RoleSwitch viewAsUser={!!viewAsUser} onToggle={onToggleViewAs} />
          </div>
        )}
        <button type="button" className={`t-btn ${styles.item}`} onClick={() => { close(); onLogout(); }}>
          <Icon name="logout" size={16} />
          Выйти
        </button>
        <button type="button" className={`t-btn ${styles.item} ${styles.itemDanger}`} onClick={() => { close(); onLogoutAll(); }}>
          Выйти на всех устройствах
        </button>
      </Dropdown>
    </div>
  );
};
