import type { FC, ReactNode } from 'react';
import styles from './BatchTabButton.module.css';
import { cx } from '../../utils/cx';

interface IBatchTabButtonProps {
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}

export const BatchTabButton: FC<IBatchTabButtonProps> = ({ active, disabled, onClick, children }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className={cx(styles.tab, active && styles.tabActive, disabled && styles.tabDisabled)}
  >
    {children}
  </button>
);
