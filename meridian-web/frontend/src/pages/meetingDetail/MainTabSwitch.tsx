import type { FC, KeyboardEvent } from 'react';
import { cx } from '../../utils/cx';
import styles from './MainTabSwitch.module.css';

export type TMainTab = 'transcript' | 'protocol';

interface IMainTabSwitchProps {
  tab: TMainTab;
  onChange: (tab: TMainTab) => void;
}

const TABS: ReadonlyArray<{ key: TMainTab; label: string }> = [
  { key: 'transcript', label: 'Транскрипт' },
  { key: 'protocol', label: 'Протокол' },
];

/** Тумблер «Транскрипт | Протокол»: подложка ездит между половинами (transform), стрелки ←/→ переключают. */
export const MainTabSwitch: FC<IMainTabSwitchProps> = ({ tab, onChange }) => {
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowRight') onChange('protocol');
    else if (e.key === 'ArrowLeft') onChange('transcript');
    else return;
    e.preventDefault();
    e.currentTarget.querySelector<HTMLElement>(`[data-tab="${e.key === 'ArrowRight' ? 'protocol' : 'transcript'}"]`)?.focus();
  };

  return (
    <div className={styles.switch} role="tablist" aria-label="Содержимое встречи" data-tab={tab} onKeyDown={handleKeyDown}>
      <span className={styles.thumb} aria-hidden />
      {TABS.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          role="tab"
          data-tab={key}
          aria-selected={tab === key}
          tabIndex={tab === key ? 0 : -1}
          className={cx(styles.btn, tab === key && styles.btnActive)}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
};
