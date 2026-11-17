/** Компактная сумма в долларах для центра кольца (≤4 символа): $7, $42, $315, $2k. */
export const formatUsdCompact = (value: number): string => {
  const v = Math.max(0, value);
  if (v >= 999.5) return `$${Math.round(v / 1000)}k`;
  return `$${Math.round(v)}`;
};

/** Точная сумма для подписи: $12.34 */
export const formatUsd = (value: number): string => `$${value.toFixed(2)}`;
