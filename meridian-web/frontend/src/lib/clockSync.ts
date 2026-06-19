// Этап 9.1: синхронизация часов устройства с backend (NTP-подобная).
// Чистые функции + framework-agnostic контроллер, переиспользуемый обоими сокетами
// (основной useWebSocket и observer-микрофон useObserverMic). Формулы зеркалят
// backend/app/services/device_clock.py.

import type { ClockSyncQuality, DeviceSyncState } from '../types';

export interface ClockSample {
  offsetMs: number;
  rttMs: number;
}

export interface ClockPong {
  seq: number;
  client_send_ms: number;
  server_receive_ms: number;
  server_send_ms: number;
}

// t0=client_send, t1=server_receive, t2=server_send, t3=client_receive
export function ntpSample(t0: number, t1: number, t2: number, t3: number): ClockSample {
  const rtt = (t3 - t0) - (t2 - t1);
  const offset = ((t1 - t0) + (t2 - t3)) / 2;
  return { offsetMs: offset, rttMs: Math.max(0, rtt) };
}

export function classifyQuality(rttMs: number): ClockSyncQuality {
  if (rttMs < 80) return 'excellent';
  if (rttMs < 200) return 'good';
  if (rttMs < 500) return 'fair';
  return 'poor';
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// Берём под-набор выборок с наименьшим RTT (точнее), offset/rtt — их медианы.
export function aggregate(samples: ClockSample[]): DeviceSyncState | null {
  if (!samples.length) return null;
  const ordered = [...samples].sort((a, b) => a.rttMs - b.rttMs);
  const keep = Math.max(1, Math.floor(ordered.length / 2));
  const best = ordered.slice(0, keep);
  const rttMs = median(best.map((s) => s.rttMs));
  return {
    offsetMs: median(best.map((s) => s.offsetMs)),
    rttMs,
    quality: classifyQuality(rttMs),
    samples: samples.length,
    lastSyncMs: Date.now(),
  };
}

const PING_COUNT = 7;
const PING_INTERVAL_MS = 300;
const RESYNC_INTERVAL_MS = 60_000;
const FLUSH_GRACE_MS = 1_500;

export interface ClockSyncOpts {
  send: (msg: { type: 'clock_ping'; seq: number; client_send_ms: number }
    | { type: 'clock_report'; offset_ms: number; rtt_ms: number; quality: ClockSyncQuality; samples_count: number }) => void;
  onResult?: (state: DeviceSyncState) => void;
}

/**
 * Гоняет серию clock_ping, собирает clock_pong, агрегирует и шлёт clock_report.
 * Имперавтиный, привязки к React нет — работает с любым WS через колбэк send.
 */
export class ClockSyncController {
  private seq = 0;
  private samples: ClockSample[] = [];
  private pending = new Map<number, number>(); // seq -> client_send_ms (t0)
  private expected = 0;
  private pingTimer: ReturnType<typeof setTimeout> | null = null;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private resyncTimer: ReturnType<typeof setInterval> | null = null;
  private running = false;
  private opts: ClockSyncOpts;

  constructor(opts: ClockSyncOpts) {
    this.opts = opts;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.runSeries();
    this.resyncTimer = setInterval(() => this.runSeries(), RESYNC_INTERVAL_MS);
  }

  stop(): void {
    this.running = false;
    if (this.pingTimer) { clearTimeout(this.pingTimer); this.pingTimer = null; }
    if (this.flushTimer) { clearTimeout(this.flushTimer); this.flushTimer = null; }
    if (this.resyncTimer) { clearInterval(this.resyncTimer); this.resyncTimer = null; }
    this.pending.clear();
    this.samples = [];
  }

  private runSeries(): void {
    this.samples = [];
    this.pending.clear();
    this.expected = 0;
    let sent = 0;
    const tick = () => {
      if (!this.running) return;
      const seq = ++this.seq;
      const t0 = Date.now();
      this.pending.set(seq, t0);
      this.expected += 1;
      this.opts.send({ type: 'clock_ping', seq, client_send_ms: t0 });
      sent += 1;
      if (sent < PING_COUNT) {
        this.pingTimer = setTimeout(tick, PING_INTERVAL_MS);
      } else {
        // подстраховка на потерю pong: отдать что собрали
        this.flushTimer = setTimeout(() => this.flush(), PING_INTERVAL_MS + FLUSH_GRACE_MS);
      }
    };
    tick();
  }

  handlePong(pong: ClockPong): void {
    const t0 = this.pending.get(pong.seq) ?? pong.client_send_ms;
    const t3 = Date.now();
    this.pending.delete(pong.seq);
    this.samples.push(ntpSample(t0, pong.server_receive_ms, pong.server_send_ms, t3));
    if (this.samples.length >= this.expected && this.expected >= PING_COUNT) {
      this.flush();
    }
  }

  private flush(): void {
    if (this.flushTimer) { clearTimeout(this.flushTimer); this.flushTimer = null; }
    const result = aggregate(this.samples);
    this.samples = [];
    this.pending.clear();
    if (!result) return;
    this.opts.send({
      type: 'clock_report',
      offset_ms: result.offsetMs,
      rtt_ms: result.rttMs,
      quality: result.quality,
      samples_count: result.samples,
    });
    this.opts.onResult?.(result);
  }
}
