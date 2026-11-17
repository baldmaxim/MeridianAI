import { describe, expect, it } from 'vitest';
import { formatUsd, formatUsdCompact } from './formatUsd';

describe('formatUsdCompact', () => {
  it('малые суммы — целые доллары', () => {
    expect(formatUsdCompact(0)).toBe('$0');
    expect(formatUsdCompact(7.4)).toBe('$7');
    expect(formatUsdCompact(42.6)).toBe('$43');
    expect(formatUsdCompact(315)).toBe('$315');
  });

  it('от 1000 — тысячи с k', () => {
    expect(formatUsdCompact(1000)).toBe('$1k');
    expect(formatUsdCompact(2400)).toBe('$2k');
    expect(formatUsdCompact(12500)).toBe('$13k');
  });

  it('отрицательное — как ноль', () => {
    expect(formatUsdCompact(-5)).toBe('$0');
  });

  it('999.6 не даёт $1000 (5 символов)', () => {
    expect(formatUsdCompact(999.6)).toBe('$1k');
  });
});

describe('formatUsd', () => {
  it('две цифры после точки', () => {
    expect(formatUsd(12.3)).toBe('$12.30');
  });
});
