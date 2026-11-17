import type { FC } from 'react';
import { getElevenLabsUsage } from '../../api/usage';
import type { IElevenLabsUsage } from '../../api/usage';
import { usePolledUsage } from '../../hooks/usePolledUsage';
import { UsageRing } from './UsageRing';

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
  const usage = usePolledUsage(getElevenLabsUsage);
  if (!usage) return null;

  const percent = Math.min(100, Math.max(0, usage.percent_used));
  return <UsageRing percent={percent} centerText={`${percent}%`} label={buildLabel(usage)} />;
};
