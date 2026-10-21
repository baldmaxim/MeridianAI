import type { FC } from 'react';
import { navTo } from '../../lib/navigation';
import { useOpenClose } from '../../hooks/useOpenClose';
import { Icon } from '../common/Icon';
import { RoleSwitch } from './RoleSwitch';
import { ThemeSegment } from './ThemeSegment';
import type { IHeaderAction, IHeaderNavModel } from './headerNav';
import styles from './HeaderMobileMenu.module.css';

interface IHeaderMobileMenuProps {
  open: boolean;
  onClose: () => void;
  nav: IHeaderNavModel;
  userName?: string;
  onLogout: () => void;
  onLogoutAll: () => void;
  canSwitchRole?: boolean;
  viewAsUser?: boolean;
  onToggleViewAs?: () => void;
}

/** Сгруппированное бургер-меню шапки (<1024px и на странице встречи). */
export const HeaderMobileMenu: FC<IHeaderMobileMenuProps> = ({ open, onClose, nav, userName, onLogout, onLogoutAll, canSwitchRole, viewAsUser, onToggleViewAs }) => {
  const menu = useOpenClose(open, { closeVar: '--dropdown-close-dur', fallbackMs: 150 });
  if (!menu.mounted) return null;

  const run = (fn: () => void) => () => { onClose(); fn(); };

  const renderItem = (label: string, action: IHeaderAction) => (
    <button
      key={label}
      type="button"
      className={`t-btn ${styles.item} ${action.active ? styles.itemActive : ''}`}
      {...navTo(action.path, run(action.onClick))}
    >
      {label}
    </button>
  );

  const sections = ([
    nav.objects && ['Проекты', nav.objects],
    nav.letters && ['Переписка', nav.letters],
    nav.knowledge && ['База знаний', nav.knowledge],
    nav.files && ['Обмен файлами', nav.files],
  ].filter(Boolean)) as [string, IHeaderAction][];

  return (
    <div className={`t-dropdown ${menu.cls} ${styles.menu}`.trim()} data-origin="top-right" role="menu">
      {nav.desktop && (
        <button
          type="button"
          className={`t-btn t-btn-amber ${styles.cta} ${nav.desktop.active ? styles.ctaActive : ''}`}
          {...navTo(nav.desktop.path, run(nav.desktop.onClick))}
        >
          <Icon name="download" size={20} />
          Приложение для ПК
        </button>
      )}

      {sections.length > 0 && (
        <>
          <div className={styles.kicker}>Разделы</div>
          {sections.map(([label, action]) => renderItem(label, action))}
        </>
      )}

      {nav.batch && (
        <>
          <div className={styles.kicker}>Модули</div>
          <button
            type="button"
            className={`t-btn ${styles.item} ${styles.module} ${nav.batch.active ? styles.moduleActive : ''}`}
            {...navTo(nav.batch.path, run(nav.batch.onClick))}
          >
            <Icon name="waveform" size={20} className={styles.moduleIcon} />
            Расшифровка записи
          </button>
        </>
      )}

      {nav.settings && (
        <button
          type="button"
          className={`t-btn ${styles.item} ${styles.settings} ${nav.settings.active ? styles.itemActive : ''}`}
          {...navTo(nav.settings.path, run(nav.settings.onClick))}
        >
          <Icon name="gear" size={20} />
          Настройки
        </button>
      )}

      <div className={styles.account}>
        {userName && (
          <div className={styles.userName}>
            <Icon name="user" size={18} />
            {userName}
          </div>
        )}
        <ThemeSegment />
        {canSwitchRole && onToggleViewAs && (
          <div className={styles.role}>
            <RoleSwitch viewAsUser={!!viewAsUser} onToggle={onToggleViewAs} />
          </div>
        )}
        <button type="button" className={`t-btn ${styles.item}`} onClick={run(onLogout)}>
          <Icon name="logout" size={18} />
          Выйти
        </button>
        <button type="button" className={`t-btn ${styles.item} ${styles.danger}`} onClick={run(onLogoutAll)}>
          Выйти на всех устройствах
        </button>
      </div>
    </div>
  );
};
