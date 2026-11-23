import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useSecondaryShadow } from './useSecondaryShadow';

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];
  readyState = 0;
  binaryType = '';
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  url: string;
  constructor(url: string) { this.url = url; MockWebSocket.instances.push(this); }
  send(data: unknown) { this.sent.push(data); }
  close() { this.readyState = MockWebSocket.CLOSED; }
  open() { this.readyState = MockWebSocket.OPEN; this.onopen?.(); }
  drop() { this.readyState = MockWebSocket.CLOSED; this.onclose?.(); }
}

class MockAudioContext {
  static last: MockAudioContext | null = null;
  state = 'running';
  onstatechange: (() => void) | null = null;
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
  constructor() { MockAudioContext.last = this; }
  createMediaStreamSource() { return { connect: vi.fn() }; }
  createMediaStreamDestination() { return {}; }
  close() { this.state = 'closed'; return Promise.resolve(); }
  setState(next: string) { this.state = next; this.onstatechange?.(); }
}

class MockWorkletNode {
  static last: MockWorkletNode | null = null;
  port: { onmessage: ((e: { data: ArrayBuffer }) => void) | null } = { onmessage: null };
  constructor() { MockWorkletNode.last = this; }
  connect = vi.fn();
  disconnect = vi.fn();
}

interface IMockTrack { readyState: string; onended: (() => void) | null; stop: () => void }
let track: IMockTrack;

const wsCount = () => MockWebSocket.instances.length;
const lastWs = () => MockWebSocket.instances[MockWebSocket.instances.length - 1];

// Один 100-мс PCM-кадр (1600 сэмплов Int16) в ворклет.
const pushChunk = () => {
  const buf = new Int16Array(1600).fill(1000).buffer;
  MockWorkletNode.last?.port.onmessage?.({ data: buf });
};

const startHook = async () => {
  const hook = renderHook(() => useSecondaryShadow(42));
  await act(async () => { await hook.result.current.start(); });
  await act(async () => { lastWs().open(); });
  return hook;
};

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.instances = [];
  localStorage.setItem('token', 'test-token');
  track = { readyState: 'live', onended: null, stop: vi.fn() };
  vi.stubGlobal('WebSocket', MockWebSocket);
  vi.stubGlobal('AudioContext', MockAudioContext);
  vi.stubGlobal('AudioWorkletNode', MockWorkletNode);
  URL.createObjectURL = vi.fn(() => 'blob:x');
  URL.revokeObjectURL = vi.fn();
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getAudioTracks: () => [track],
        getTracks: () => [track],
      }),
    },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('useSecondaryShadow: прерывание и реконнект', () => {
  it('неожиданный close переоткрывает WS через 1с, seq продолжается', async () => {
    const { result } = await startHook();
    expect(result.current.active).toBe(true);

    act(() => { pushChunk(); });
    const first = lastWs();
    expect(first.sent.length).toBeGreaterThan(1); // enable_secondary_shadow + кадр

    act(() => { first.drop(); });
    expect(wsCount()).toBe(1);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(wsCount()).toBe(2);

    await act(async () => { lastWs().open(); });
    act(() => { pushChunk(); });
    const frames = lastWs().sent.filter((d) => d instanceof ArrayBuffer) as ArrayBuffer[];
    expect(frames).toHaveLength(1);
    const view = new DataView(frames[0]);
    const header = JSON.parse(new TextDecoder().decode(new Uint8Array(frames[0], 2, view.getUint16(0, false))));
    expect(header.seq).toBe(2);
    expect(result.current.active).toBe(true);
    expect(result.current.interrupted).toBe(false);
  });

  it('пять неудачных попыток → interrupted без error', async () => {
    const { result } = await startHook();
    act(() => { lastWs().drop(); });
    for (let i = 0; i < 5; i++) {
      act(() => { vi.advanceTimersByTime(4000); });
      expect(wsCount()).toBe(2 + i);
      act(() => { lastWs().drop(); });
    }
    expect(result.current.interrupted).toBe(true);
    expect(result.current.active).toBe(false);
    expect(result.current.error).toBeNull();
    expect(wsCount()).toBe(6);
  });

  it('stop() и unmount не порождают новый сокет', async () => {
    const { result, unmount } = await startHook();
    act(() => { result.current.stop(); });
    act(() => { vi.advanceTimersByTime(10000); });
    expect(wsCount()).toBe(1);
    expect(result.current.interrupted).toBe(false);

    const second = await startHook();
    const n = wsCount();
    second.unmount();
    act(() => { vi.advanceTimersByTime(10000); });
    expect(wsCount()).toBe(n);
    unmount();
  });

  it('AudioContext interrupted → interrupted=true, без error; повторный start сбрасывает флаг', async () => {
    const { result } = await startHook();
    act(() => { MockAudioContext.last?.setState('interrupted'); });
    expect(result.current.interrupted).toBe(true);
    expect(result.current.active).toBe(false);
    expect(result.current.error).toBeNull();

    await act(async () => { await result.current.start(); });
    expect(result.current.interrupted).toBe(false);
    expect(result.current.active).toBe(true);
  });

  it('track.onended → interrupted', async () => {
    const { result } = await startHook();
    act(() => { track.onended?.(); });
    expect(result.current.interrupted).toBe(true);
    expect(result.current.active).toBe(false);
  });

  it('реконнект ждёт видимости вкладки', async () => {
    const { result } = await startHook();
    const vis = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    act(() => { lastWs().drop(); });
    act(() => { vi.advanceTimersByTime(10000); });
    expect(wsCount()).toBe(1);

    vis.mockReturnValue('visible');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(wsCount()).toBe(2);
    expect(result.current.interrupted).toBe(false);
    vis.mockRestore();
  });
});
