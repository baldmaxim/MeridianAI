import type { FC } from 'react';
import { getElevenLabsUsage } from '../../api/usage';
import { usePolledUsage } from '../../hooks/usePolledUsage';
import { buildCreditsLabel } from './creditsLabel';
import { UsageRing } from './UsageRing';
import styles from './CreditsRing.module.css';

interface ICreditsRingProps {
  /** Показать рядом с кольцом текст остатка (панель «Лимиты» на мобильном) */
  showText?: boolean;
}

/** Кольцо расхода кредитов ElevenLabs в шапке. Загрузка/ошибка — ничего не рисуем. */
export const CreditsRing: FC<ICreditsRingProps> = ({ showText = false }) => {
  const usage = usePolledUsage(getElevenLabsUsage);
  if (!usage) return null;

  const percent = Math.min(100, Math.max(0, usage.percent_used));
  const label = buildCreditsLabel(usage);
  const ring = <UsageRing percent={percent} centerText={`${percent}%`} label={label} />;
  if (!showText) return ring;

  return (
    <div className={styles.row}>
      {ring}
      <span className={styles.text}>{label}</span>
    </div>
  );
};
