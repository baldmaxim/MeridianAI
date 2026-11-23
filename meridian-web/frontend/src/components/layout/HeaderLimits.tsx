import { useCallback, useState } from 'react';
import type { FC } from 'react';
import { Dropdown } from '../common/Dropdown';
import { Icon } from '../common/Icon';
import { CreditsRing } from './CreditsRing';
import { OpenRouterBalance } from './OpenRouterBalance';
import headerStyles from './Header.module.css';
import styles from './HeaderLimits.module.css';

interface IHeaderLimitsProps {
  /** Админ: показывать строку OpenRouter */
  isAdmin?: boolean;
}

/**
 * Лимиты на мобильном: одна кнопка в шапке, по тапу — панель со строками «Распознавание» и (админу) «OpenRouter».
 * Кольца монтируются только при открытой панели (иначе на мобиле нет лишнего опроса) —
 * данные подгружаются в момент открытия.
 */
export const HeaderLimits: FC<IHeaderLimitsProps> = ({ isAdmin = false }) => {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  return (
    <>
      <button
        type="button"
        className={`t-btn ${headerStyles.iconBtn} ${open ? headerStyles.iconBtnActive : ''}`}
        aria-label="Лимиты"
        title="Лимиты"
        aria-haspopup="true"
        aria-expanded={open}
        // mousedown вне панели закрывает Dropdown — не даём ему сработать на самом триггере
        onMouseDown={(e) => e.nativeEvent.stopPropagation()}
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="gauge" size={20} />
      </button>
      <Dropdown open={open} onClose={close} origin="top-right" className={styles.panel}>
        <div className={styles.row}>
          <div className={styles.rowLabel}>Распознавание (ElevenLabs)</div>
          <CreditsRing showText />
        </div>
        {isAdmin && (
          <div className={styles.row}>
            <div className={styles.rowLabel}>OpenRouter</div>
            <div className={styles.rowValue}>
              <OpenRouterBalance alwaysShowPrefix />
            </div>
          </div>
        )}
      </Dropdown>
    </>
  );
};
