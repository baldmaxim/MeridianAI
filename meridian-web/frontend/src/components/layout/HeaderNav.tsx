import { useCallback, useState } from 'react';
import type { FC } from 'react';
import { navTo } from '../../lib/navigation';
import { Dropdown } from '../common/Dropdown';
import { Icon } from '../common/Icon';
import type { IHeaderAction, IHeaderNavModel } from './headerNav';
import styles from './HeaderNav.module.css';

interface IHeaderNavProps {
  nav: IHeaderNavModel;
}

interface IMaterialItem {
  key: string;
  label: string;
  hint: string;
  action: IHeaderAction;
}

/** Десктопная навигация шапки (≥1024px): табы-разделы, чип модуля и CTA «Скачать для ПК». */
export const HeaderNav: FC<IHeaderNavProps> = ({ nav }) => {
  const [materialsOpen, setMaterialsOpen] = useState(false);
  const closeMaterials = useCallback(() => setMaterialsOpen(false), []);

  const materials = ([
    nav.letters && { key: 'letters', label: 'Переписка', hint: 'Поиск по письмам PayHub', action: nav.letters },
    nav.knowledge && { key: 'knowledge', label: 'База знаний', hint: 'Знания, собранные из встреч', action: nav.knowledge },
    nav.files && { key: 'files', label: 'Обмен файлами', hint: 'Личная флешка между устройствами', action: nav.files },
  ].filter(Boolean)) as IMaterialItem[];
  const materialsActive = materials.some((m) => m.action.active);

  return (
    <nav className={styles.nav} aria-label="Разделы">
      {nav.objects && (
        <button
          type="button"
          className={`${styles.tab} ${nav.objects.active ? styles.tabActive : ''}`}
          aria-current={nav.objects.active ? 'page' : undefined}
          {...navTo(nav.objects.path, nav.objects.onClick)}
        >
          Проекты
        </button>
      )}

      {materials.length > 0 && (
        <div className={styles.materialsWrap}>
          <button
            type="button"
            className={`${styles.tab} ${materialsActive ? styles.tabActive : ''}`}
            aria-haspopup="menu"
            aria-expanded={materialsOpen}
            // mousedown вне меню закрывает Dropdown — не даём ему сработать на самом триггере
            onMouseDown={(e) => e.nativeEvent.stopPropagation()}
            onClick={() => setMaterialsOpen((o) => !o)}
          >
            Материалы
            <Icon name="chevron-down" size={14} className={`${styles.chevron} ${materialsOpen ? styles.chevronOpen : ''}`} />
          </button>
          <Dropdown open={materialsOpen} onClose={closeMaterials} origin="top-left" className={styles.materialsMenu}>
            {materials.map((m) => (
              <button
                key={m.key}
                type="button"
                role="menuitem"
                className={`${styles.materialItem} ${m.action.active ? styles.materialItemActive : ''}`}
                {...navTo(m.action.path, () => { closeMaterials(); m.action.onClick(); })}
              >
                <span className={styles.materialLabel}>{m.label}</span>
                <span className={styles.materialHint}>{m.hint}</span>
              </button>
            ))}
          </Dropdown>
        </div>
      )}

      {nav.batch && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <button
            type="button"
            className={`${styles.chip} ${nav.batch.active ? styles.chipActive : ''}`}
            aria-current={nav.batch.active ? 'page' : undefined}
            {...navTo(nav.batch.path, nav.batch.onClick)}
          >
            <Icon name="waveform" size={20} className={styles.chipIcon} />
            <span className={styles.chipText}>
              <span className={styles.chipKicker}>Модуль</span>
              <span className={styles.chipLabel}>Расшифровка записи</span>
            </span>
          </button>
        </>
      )}

      {nav.desktop && (
        <button
          type="button"
          className={`t-btn t-btn-amber ${styles.cta} ${nav.desktop.active ? styles.ctaActive : ''}`}
          aria-current={nav.desktop.active ? 'page' : undefined}
          {...navTo(nav.desktop.path, nav.desktop.onClick)}
        >
          <Icon name="download" size={16} />
          Скачать для ПК
        </button>
      )}
    </nav>
  );
};
