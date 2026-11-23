import { useEffect, useRef, useState } from 'react';
import type { FC, ReactNode } from 'react';
import { Collapse } from '../common/Collapse';
import styles from './SourceTreeFolder.module.css';

interface ISourceTreeFolderProps {
  title: string;
  defaultOpen?: boolean;
  /** Мелкий счётчик справа: «N из M». Без него — не показывается. */
  counter?: string;
  /** Состояние чекбокса «включить всю группу». Без пропа чекбокса нет. */
  checked?: 'all' | 'some' | 'none';
  onToggleAll?: () => void;
  checkLabel?: string;
  /** Дополнительные элементы справа (кнопки). */
  right?: ReactNode;
  children: ReactNode;
}

/** Папка дерева источников: шеврон, иконка, название, счётчик; содержимое — с отступом, без рамок и фона. */
export const SourceTreeFolder: FC<ISourceTreeFolderProps> = ({
  title, defaultOpen = false, counter, checked, onToggleAll, checkLabel, right, children,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  const checkRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (checkRef.current) checkRef.current.indeterminate = checked === 'some';
  }, [checked]);

  return (
    <div className={styles.folder}>
      <div className={styles.head}>
        <button
          type="button"
          className={styles.toggle}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <span className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`} aria-hidden>▶</span>
          <svg className={styles.icon} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          </svg>
          <span className={styles.title}>{title}</span>
        </button>
        {counter && <span className={styles.counter}>{counter}</span>}
        {right}
        {checked && onToggleAll && (
          <label className={styles.checkLabel}>
            <input
              ref={checkRef}
              type="checkbox"
              className={styles.checkbox}
              checked={checked === 'all'}
              onChange={onToggleAll}
              aria-label={checkLabel ?? `Включить всю группу «${title}»`}
            />
          </label>
        )}
      </div>
      <Collapse open={open} className={styles.body}>{children}</Collapse>
    </div>
  );
};
