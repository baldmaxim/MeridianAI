import { describe, expect, it } from 'vitest';
import { resolveTypeColor } from './suggestionStyles';

describe('resolveTypeColor', () => {
  it('стандартные hex старых настроек заменяет токенами темы', () => {
    expect(resolveTypeColor('#F5A623')).toBe('var(--accent-amber)');
    expect(resolveTypeColor('#2ee59d')).toBe('var(--accent-green)');
  });

  it('пользовательский цвет оставляет как есть', () => {
    expect(resolveTypeColor('#123456')).toBe('#123456');
  });
});
