import { useState } from 'react';
import type { FC, ReactNode } from 'react';
import { Collapse } from './Collapse';
import styles from './CollapsibleSection.module.css';

interface ICollapsibleSectionProps {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
  right?: ReactNode;
}

export const CollapsibleSection: FC<ICollapsibleSectionProps> = ({ title, defaultOpen, children, right }) => {
  const [open, setOpen] = useState(defaultOpen ?? false);

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className={styles.toggle}
        >
          <span className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}>▶</span>
          <span className={styles.dot} />
          <span className={styles.title}>{title}</span>
        </button>
        {right && <div className={styles.right}>{right}</div>}
      </div>
      <Collapse open={open} className={styles.body}>{children}</Collapse>
    </div>
  );
};
