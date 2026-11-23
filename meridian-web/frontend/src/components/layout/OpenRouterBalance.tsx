import { useEffect, useRef, useState } from 'react';
import type { FC } from 'react';
import { getOpenRouterUsage } from '../../api/usage';
import { usePolledUsage } from '../../hooks/usePolledUsage';
import { formatUsd } from '../../lib/formatUsd';
import styles from './OpenRouterBalance.module.css';

interface IOpenRouterBalanceProps {
  /** Префикс («Ключ»/«Баланс») виден всегда, а не только от 768px (панель «Лимиты» на мобильном) */
  alwaysShowPrefix?: boolean;
}

/** Пилюля остатка OpenRouter в шапке (только админ): по лимиту ключа или баланс аккаунта. Загрузка/ошибка/403/null — ничего не рисуем. */
export const OpenRouterBalance: FC<IOpenRouterBalanceProps> = ({ alwaysShowPrefix = false }) => {
  const usage = usePolledUsage(getOpenRouterUsage);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Тап по пилюле открывает подсказку (title на тач-устройствах не показывается); тап снаружи — закрывает
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [open]);

  if (!usage || usage.balance === null) return null;

  const amount = formatUsd(usage.balance);
  const isKey = usage.source === 'key';
  const prefix = isKey ? 'Ключ' : 'Баланс';
  const label = isKey ? `OpenRouter: осталось по ключу ${amount}` : `Баланс OpenRouter: ${amount}`;

  return (
    <div ref={wrapRef} className={styles.wrap}>
      <button
        type="button"
        className={styles.pill}
        title={label}
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={alwaysShowPrefix ? styles.prefixAlways : styles.prefix}>{prefix}</span>
        <span>{amount}</span>
      </button>
      {open && <div role="tooltip" className={styles.tip}>{label}</div>}
    </div>
  );
};
