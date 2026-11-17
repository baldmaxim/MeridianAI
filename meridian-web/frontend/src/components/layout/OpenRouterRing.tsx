import type { FC } from 'react';
import { getOpenRouterUsage } from '../../api/usage';
import type { IOpenRouterUsage } from '../../api/usage';
import { usePolledUsage } from '../../hooks/usePolledUsage';
import { formatUsd, formatUsdCompact } from '../../lib/formatUsd';
import { UsageRing } from './UsageRing';

const buildLabel = (u: IOpenRouterUsage): string =>
  u.total !== null && u.remaining !== null
    ? `OpenRouter: осталось ${formatUsd(u.remaining)} из ${formatUsd(u.total)}`
    : `OpenRouter: израсходовано ${formatUsd(u.used)}`;

/** Кольцо баланса OpenRouter в шапке (только админ). Загрузка/ошибка/403 — ничего не рисуем. */
export const OpenRouterRing: FC = () => {
  const usage = usePolledUsage(getOpenRouterUsage);
  if (!usage) return null;

  return (
    <UsageRing
      percent={usage.percent_used}
      centerText={formatUsdCompact(usage.remaining ?? usage.used)}
      label={buildLabel(usage)}
    />
  );
};
