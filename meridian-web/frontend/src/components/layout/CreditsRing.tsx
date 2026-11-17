import { useEffect, useRef, useState } from 'react';
import type { FC } from 'react';
import { getElevenLabsUsage } from '../../api/usage';
import type { IElevenLabsUsage } from '../../api/usage';
import styles from './CreditsRing.module.css';

const REFRESH_MS = 5 * 60 * 1000;
const WARN_PERCENT = 80;

const fmt = (n: number): string => n.toLocaleString('ru-RU');

/** «2026-12-05» → «05.12» */
const fmtReset = (iso: string): string => {
  const [, m, d] = iso.split('-');
  return d && m ? `${d}.${m}` : iso;
};

const buildLabel = (u: IElevenLabsUsage): string => {
  const base = `ElevenLabs: осталось ${fmt(u.remaining)} из ${fmt(u.limit)} кредитов`;
  return u.next_reset ? `${base} · сброс ${fmtReset(u.next_reset)}` : base;
};

/** Кольцо расхода кредитов ElevenLabs в шапке. Загрузка/ошибка — ничего не рисуем. */
export const CreditsRing: FC = () => {
  const [usage, setUsage] = useState<IElevenLabsUsage | null>(null);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const load = () => {
      getElevenLabsUsage()
        .then((u) => { if (alive) setUsage(u); })
        .catch(() => { if (alive) setUsage(null); });
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    window.addEventListener('focus', load);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener('focus', load);
    };
  }, []);

  // Тап по кольцу открывает подсказку (title на тач-устройствах не показывается); тап снаружи — закрывает
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [open]);

  if (!usage) return null;

  const percent = Math.min(100, Math.max(0, usage.percent_used));
  const label = buildLabel(usage);

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
        <span className={styles.pct}>{percent}%</span>
      </button>
      {open && <div role="tooltip" className={styles.tip}>{label}</div>}
    </div>
  );
};
