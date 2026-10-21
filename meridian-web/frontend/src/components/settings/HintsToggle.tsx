import type { FC } from 'react';
import styles from './HintsToggle.module.css';
import { cx } from '../../utils/cx';

interface IHintsToggleProps {
  checked: boolean;
  onToggle: () => void;
}

/** Переключатель «вкл/выкл» для типов подсказок и триггеров. */
export const HintsToggle: FC<IHintsToggleProps> = ({ checked, onToggle }) => (
  <div className={cx(styles.toggle, checked && styles.toggleOn)} onClick={onToggle}>
    <div className={styles.toggleKnob} />
  </div>
);
