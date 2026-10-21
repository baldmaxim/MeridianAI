import { describe, expect, it } from 'vitest';
import { isCacheableApiRequest, isNeverCachedRequest, pwaOptions } from '../vite.pwa.config';

/**
 * Страховка конфига PWA: чувствительные маршруты не должны попасть в SW-кэш,
 * обновление — только по подтверждению пользователя.
 */
const ORIGIN = 'https://meridian.test';

const match = (path: string, init: { sameOrigin?: boolean; headers?: Record<string, string> } = {}) => {
  const url = new URL(path, ORIGIN);
  const args = {
    url,
    sameOrigin: init.sameOrigin ?? true,
    request: new Request(url, { headers: init.headers }),
  };
  return { never: isNeverCachedRequest(args), api: isCacheableApiRequest(args) };
};

describe('PWA config', () => {
  it("registerType: 'prompt', skipWaiting не включён", () => {
    expect(pwaOptions.registerType).toBe('prompt');
    expect(pwaOptions.workbox?.skipWaiting).toBeFalsy();
  });

  it('манифест содержит обязательные поля и иконки 192/512/maskable/svg', () => {
    const m = pwaOptions.manifest;
    if (!m) throw new Error('manifest не задан');
    expect(m.name).toBeTruthy();
    expect(m.short_name).toBeTruthy();
    expect(m.start_url).toBe('/');
    expect(m.display).toBe('standalone');
    expect(m.background_color).toBeTruthy();
    expect(m.theme_color).toBeTruthy();
    const icons = m.icons ?? [];
    expect(icons.some((i) => i.sizes === '192x192')).toBe(true);
    expect(icons.some((i) => i.sizes === '512x512' && !i.purpose)).toBe(true);
    expect(icons.some((i) => i.sizes === '512x512' && i.purpose === 'maskable')).toBe(true);
    expect(icons.some((i) => i.type === 'image/svg+xml')).toBe(true);
  });

  it('/api/auth/*, скачивания, /ws, /s3, /health — NetworkOnly, не в api-cache', () => {
    for (const p of [
      '/api/auth/login',
      '/api/auth/me',
      '/api/transcriptions/5/download?token=abc',
      '/api/batch/jobs/3/download/txt',
      '/api/stash/12/download-url',
      '/ws/meeting?token=abc',
      '/s3/bucket/file.wav?X-Amz-Signature=1',
      '/health/ready',
    ]) {
      const r = match(p);
      expect(r.never, p).toBe(true);
      expect(r.api, p).toBe(false);
    }
  });

  it('Range-запросы и чужие хосты не кэшируются', () => {
    expect(match('/api/batch/jobs/1/audio', { headers: { range: 'bytes=0-1' } }).api).toBe(false);
    expect(match('/api/meetings', { sameOrigin: false }).api).toBe(false);
  });

  it('обычные GET /api/* — NetworkFirst с api-cache', () => {
    const r = match('/api/meetings');
    expect(r.never).toBe(false);
    expect(r.api).toBe(true);

    const rule = pwaOptions.workbox?.runtimeCaching?.find((c) => c.handler === 'NetworkFirst');
    expect(rule?.options?.cacheName).toBe('api-cache');
    expect(rule?.options?.networkTimeoutSeconds).toBe(5);
    expect(rule?.options?.expiration).toEqual({ maxEntries: 50, maxAgeSeconds: 86400 });
  });

  it('правило NetworkOnly стоит раньше NetworkFirst', () => {
    const handlers = pwaOptions.workbox?.runtimeCaching?.map((c) => c.handler);
    expect(handlers).toEqual(['NetworkOnly', 'NetworkFirst']);
  });

  it('navigateFallback отдаёт index.html, но не для API/WS/S3/health/desktop', () => {
    const wb = pwaOptions.workbox;
    expect(wb?.navigateFallback).toBe('/index.html');
    const deny = wb?.navigateFallbackDenylist ?? [];
    for (const p of ['/api/meetings', '/ws/meeting', '/s3/x', '/health/live', '/desktop/latest.json']) {
      expect(
        deny.some((re) => re.test(p)),
        p,
      ).toBe(true);
    }
    expect(deny.some((re) => re.test('/meetings/42'))).toBe(false);
  });
});
