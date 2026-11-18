import { describe, expect, it } from 'vitest';
import { desktopCallbackUrl, parseDesktopLoginParams } from './desktopLogin';

const STATE = 'a1b2c3d4e5f6g7h8_-xyz';
const CHALLENGE = 'ab'.repeat(32);
const qs = (p: Record<string, string>) => '?' + new URLSearchParams(p).toString();

describe('parseDesktopLoginParams', () => {
  it('принимает корректные параметры', () => {
    expect(parseDesktopLoginParams(qs({ port: '53012', state: STATE, challenge: CHALLENGE })))
      .toEqual({ port: 53012, state: STATE, challenge: CHALLENGE });
  });

  it('границы порта', () => {
    const p = (port: string) => parseDesktopLoginParams(qs({ port, state: STATE, challenge: CHALLENGE }));
    expect(p('1024')).not.toBeNull();
    expect(p('65535')).not.toBeNull();
    expect(p('1023')).toBeNull();
    expect(p('65536')).toBeNull();
    expect(p('80')).toBeNull();
    expect(p('12.5')).toBeNull();
    expect(p('abc')).toBeNull();
    expect(p('')).toBeNull();
  });

  it('отклоняет плохие state и challenge', () => {
    const p = (state: string, challenge: string) =>
      parseDesktopLoginParams(qs({ port: '53012', state, challenge }));
    expect(p('short', CHALLENGE)).toBeNull();
    expect(p('x'.repeat(129), CHALLENGE)).toBeNull();
    expect(p('bad state with spaces!!', CHALLENGE)).toBeNull();
    expect(p(STATE, CHALLENGE.toUpperCase())).toBeNull();
    expect(p(STATE, CHALLENGE.slice(1))).toBeNull();
    expect(p(STATE, 'z'.repeat(64))).toBeNull();
  });

  it('пустая строка запроса', () => {
    expect(parseDesktopLoginParams('')).toBeNull();
  });
});

describe('desktopCallbackUrl', () => {
  it('код и state', () => {
    expect(desktopCallbackUrl({ port: 53012, state: STATE }, { code: 'a-b_c' }))
      .toBe(`http://127.0.0.1:53012/callback?code=a-b_c&state=${STATE}`);
  });

  it('отказ', () => {
    expect(desktopCallbackUrl({ port: 53012, state: STATE }, { error: 'access_denied' }))
      .toBe(`http://127.0.0.1:53012/callback?error=access_denied&state=${STATE}`);
  });
});
