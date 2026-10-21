import { afterEach, describe, expect, it } from 'vitest';
import { getCssVar, withAlpha } from './cssVar';

afterEach(() => {
  document.documentElement.style.removeProperty('--accent');
});

describe('withAlpha', () => {
  it('оборачивает var() в color-mix с процентом', () => {
    expect(withAlpha('var(--accent)', 20)).toBe('color-mix(in srgb, var(--accent) 20%, transparent)');
  });

  it('работает с hex', () => {
    expect(withAlpha('#F5A623', 8)).toBe('color-mix(in srgb, #F5A623 8%, transparent)');
  });
});

describe('getCssVar', () => {
  it('читает переменную по имени и по var(...)', () => {
    document.documentElement.style.setProperty('--accent', ' #123456 ');
    expect(getCssVar('--accent')).toBe('#123456');
    expect(getCssVar('var(--accent)')).toBe('#123456');
    expect(getCssVar('var( --accent , #000)')).toBe('#123456');
  });

  it('отдаёт fallback, если переменной нет', () => {
    expect(getCssVar('--no-such-var', 'red')).toBe('red');
    expect(getCssVar('var(--no-such-var)')).toBe('');
  });
});
