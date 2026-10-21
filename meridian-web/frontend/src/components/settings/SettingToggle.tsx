import type { FC } from 'react';
import styles from './SettingToggle.module.css';
import { cx } from '../../utils/cx';

interface ISettingToggleProps {
  checked: boolean;
  onToggle: () => void;
  label: string;
  description: string;
  disabled?: boolean;
}

/** Строка настройки с переключателем «вкл/выкл» (название, описание, тумблер). */
export const SettingToggle: FC<ISettingToggleProps> = ({ checked, onToggle, label, description, disabled }) => {
  const on = checked && !disabled;
  return (
    <div
      className={cx(styles.toggleRow, disabled && styles.toggleRowDisabled)}
      onClick={disabled ? undefined : onToggle}
    >
      <div>
        <div className={styles.toggleLabel}>{label}</div>
        <div className={styles.toggleDesc}>{description}</div>
      </div>
      <div className={cx(styles.toggle, on && styles.toggleOn)}>
        <div className={styles.toggleKnob} />
      </div>
    </div>
  );
};
