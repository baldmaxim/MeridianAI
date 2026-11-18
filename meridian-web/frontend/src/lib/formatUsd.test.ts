import { describe, expect, it } from 'vitest';
import { formatUsd } from './formatUsd';

describe('formatUsd', () => {
  it('две цифры после точки', () => {
    expect(formatUsd(12.3)).toBe('$12.30');
  });
});
