import { afterEach, describe, it, expect, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { createRef } from 'react';
import type { RefObject } from 'react';
import { useActiveWord } from './useActiveWord';
import type { IAlignedToken } from './alignWords';

const TOKENS: IAlignedToken[] = [
  { text: 'один', start: 1, end: 1.4 },
  { text: ' ', start: null, end: null },
  { text: 'два', start: 2, end: 2.4 },
  { text: ' ', start: null, end: null },
  { text: 'три', start: 5, end: 5.4 },
];

const Probe = ({ audioRef, enabled }: { audioRef: RefObject<HTMLAudioElement | null>; enabled: boolean }) => {
  const idx = useActiveWord(audioRef, TOKENS, enabled);
  return <output>{idx}</output>;
};

const setup = (enabled = true) => {
  const audio = document.createElement('audio');
  const audioRef = createRef<HTMLAudioElement>() as { current: HTMLAudioElement | null };
  audioRef.current = audio;
  const view = render(<Probe audioRef={audioRef} enabled={enabled} />);
  const out = () => view.container.querySelector('output')?.textContent;
  const setTime = (time: number) => {
    Object.defineProperty(audio, 'currentTime', { value: time, configurable: true });
  };
  const at = (time: number, event = 'timeupdate') => {
    setTime(time);
    act(() => { audio.dispatchEvent(new Event(event)); });
  };
  return { view, out, at, setTime, audio };
};

describe('useActiveWord', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('индекс — последнее слово со start <= currentTime + 0.05; до первого — -1', () => {
    const { out, at } = setup();
    expect(out()).toBe('-1');
    at(0.96, 'seeked');
    expect(out()).toBe('0');
    at(2.2);
    expect(out()).toBe('2');
    at(4.96, 'seeked');
    expect(out()).toBe('4');
    at(0.5, 'seeked');
    expect(out()).toBe('-1');
  });

  it('пауза дольше end + 0.6 — подсветка гаснет', () => {
    const { out, at } = setup();
    at(2.2);
    expect(out()).toBe('2');
    at(2.95, 'seeked'); // 2.95 <= 2.4 + 0.6 — ещё держится
    expect(out()).toBe('2');
    at(3.1);
    expect(out()).toBe('-1');
    at(6.5);
    expect(out()).toBe('-1');
  });

  it('выключено — -1', () => {
    const { out, at } = setup(false);
    at(2.2);
    expect(out()).toBe('-1');
  });

  it('при воспроизведении обновляется по requestAnimationFrame, на паузе цикл останавливается', () => {
    const callbacks = new Map<number, FrameRequestCallback>();
    let nextId = 1;
    const raf = vi.fn((cb: FrameRequestCallback) => {
      const id = nextId;
      nextId += 1;
      callbacks.set(id, cb);
      return id;
    });
    const caf = vi.fn((id: number) => { callbacks.delete(id); });
    vi.stubGlobal('requestAnimationFrame', raf);
    vi.stubGlobal('cancelAnimationFrame', caf);
    const { out, setTime, audio } = setup();
    Object.defineProperty(audio, 'paused', { value: false, configurable: true });
    act(() => { audio.dispatchEvent(new Event('play')); });
    expect(callbacks.size).toBe(1);
    setTime(2.1);
    act(() => { [...callbacks.values()][0](0); });
    expect(out()).toBe('2');
    expect(callbacks.size).toBe(2);
    act(() => { audio.dispatchEvent(new Event('pause')); });
    expect(caf).toHaveBeenCalled();
    expect(callbacks.size).toBe(1);
  });

  it('размонтирование отменяет цикл', () => {
    const callbacks = new Map<number, FrameRequestCallback>();
    let nextId = 1;
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      const id = nextId;
      nextId += 1;
      callbacks.set(id, cb);
      return id;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => { callbacks.delete(id); });
    const { view, audio } = setup();
    Object.defineProperty(audio, 'paused', { value: false, configurable: true });
    act(() => { audio.dispatchEvent(new Event('play')); });
    expect(callbacks.size).toBe(1);
    view.unmount();
    expect(callbacks.size).toBe(0);
  });
});
