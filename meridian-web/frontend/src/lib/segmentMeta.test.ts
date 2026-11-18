import { describe, it, expect } from 'vitest';
import { foreignLanguageBadge, formatDiarizedSpeaker, uniqueInOrder } from './segmentMeta';

describe('segmentMeta', () => {
  it('бейдж языка: только известный нерусский', () => {
    expect(foreignLanguageBadge('tr')).toBe('TR');
    expect(foreignLanguageBadge('eng')).toBe('ENG');
    expect(foreignLanguageBadge('en-US')).toBe('EN');
    expect(foreignLanguageBadge('ru')).toBeNull();
    expect(foreignLanguageBadge('RUS')).toBeNull();
    expect(foreignLanguageBadge(null)).toBeNull();
    expect(foreignLanguageBadge(undefined)).toBeNull();
  });

  it('метка диаризации → «Спикер N»', () => {
    expect(formatDiarizedSpeaker('s1_speaker_0')).toBe('Спикер 1');
    expect(formatDiarizedSpeaker('s1_speaker_2')).toBe('Спикер 3');
    expect(formatDiarizedSpeaker('s2_speaker_0')).toBe('Спикер 1 (сессия 2)');
    expect(formatDiarizedSpeaker('Заказчик')).toBe('Заказчик');
  });

  it('uniqueInOrder', () => {
    expect(uniqueInOrder(['a', 'b', 'a'])).toEqual(['a', 'b']);
  });
});
