import { describe, expect, it } from 'vitest';
import { swipeDirection } from './useHorizontalSwipe';

describe('swipeDirection', () => {
  it('порог 50px по X и |dx| > |dy|', () => {
    expect(swipeDirection(-80, 10)).toBe('left');
    expect(swipeDirection(80, -10)).toBe('right');
    expect(swipeDirection(-49, 0)).toBeNull();
    expect(swipeDirection(-60, 90)).toBeNull();
    expect(swipeDirection(60, 60)).toBeNull();
  });
});
