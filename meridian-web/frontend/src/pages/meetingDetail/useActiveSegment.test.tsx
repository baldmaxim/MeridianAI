import { afterEach, describe, it, expect } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { createRef } from 'react';
import type { RefObject } from 'react';
import { useActiveSegment } from './useActiveSegment';

const STARTS = [0, 5, 10];

const Probe = ({ audioRef, enabled }: { audioRef: RefObject<HTMLAudioElement | null>; enabled: boolean }) => {
  const idx = useActiveSegment(audioRef, STARTS, enabled);
  return <output>{idx}</output>;
};

const setup = (enabled: boolean) => {
  const audio = document.createElement('audio');
  const audioRef = createRef<HTMLAudioElement>() as { current: HTMLAudioElement | null };
  audioRef.current = audio;
  const view = render(<Probe audioRef={audioRef} enabled={enabled} />);
  const at = (time: number, event = 'timeupdate') => {
    Object.defineProperty(audio, 'currentTime', { value: time, configurable: true });
    act(() => { audio.dispatchEvent(new Event(event)); });
  };
  return { view, at, audio, audioRef };
};

describe('useActiveSegment', () => {
  afterEach(cleanup);

  it('активная реплика — последняя со start <= currentTime', () => {
    const { view, at } = setup(true);
    expect(view.container.querySelector('output')?.textContent).toBe('0');
    at(7);
    expect(view.container.querySelector('output')?.textContent).toBe('1');
    at(10, 'seeked');
    expect(view.container.querySelector('output')?.textContent).toBe('2');
    at(4.95, 'seeked');
    expect(view.container.querySelector('output')?.textContent).toBe('1');
  });

  it('выключено — -1 и без подписки', () => {
    const { view, at } = setup(false);
    expect(view.container.querySelector('output')?.textContent).toBe('-1');
    at(7);
    expect(view.container.querySelector('output')?.textContent).toBe('-1');
  });

  it('включение после появления элемента подхватывает текущее время', () => {
    const { view, audio, audioRef } = setup(false);
    Object.defineProperty(audio, 'currentTime', { value: 6, configurable: true });
    view.rerender(<Probe audioRef={audioRef} enabled />);
    expect(view.container.querySelector('output')?.textContent).toBe('1');
  });
});
