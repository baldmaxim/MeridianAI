import { useEffect, useRef, useState } from 'react';
import type { FC } from 'react';
import styles from './UsageRing.module.css';

const WARN_PERCENT = 80;

interface IUsageRingProps {
  /** Доля расхода, 0–100 */
  percent: number;
  /** Текст в центре кольца */
  centerText: string;
  /** Подпись: title, aria-label и подсказка по тапу */
  label: string;
}

/** Кольцо расхода в шапке (презентационное): дуга, центр, подсказка по тапу. */
export const UsageRing: FC<IUsageRingProps> = ({ percent: rawPercent, centerText, label }) => {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Тап по кольцу открывает подсказку (title на тач-устройствах не показывается); тап снаружи — закрывает
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [open]);

  const percent = Math.min(100, Math.max(0, rawPercent));

  return (
    <div ref={wrapRef} className={styles.wrap}>
      <button
        type="button"
        className={`${styles.ring} ${percent >= WARN_PERCENT ? styles.warn : ''}`}
        title={label}
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <svg className={styles.svg} viewBox="0 0 28 28" aria-hidden="true">
          <circle className={styles.track} cx="14" cy="14" r="11.5" pathLength={100} />
          <circle
            className={styles.arc}
            cx="14"
            cy="14"
            r="11.5"
            pathLength={100}
            strokeDasharray={`${percent} 100`}
          />
        </svg>
        <span className={styles.pct}>{centerText}</span>
      </button>
      {open && <div role="tooltip" className={styles.tip}>{label}</div>}
    </div>
  );
};
