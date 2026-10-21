import type { VitePWAOptions } from 'vite-plugin-pwa'
import { API_CACHE_NAME } from './src/lib/swCache'

/**
 * Конфиг PWA (vite-plugin-pwa, generateSW). Вынесен из vite.config.ts,
 * чтобы его можно было проверить тестом (src/pwaConfig.test.ts).
 *
 * Матчеры runtimeCaching — самодостаточные функции: workbox сериализует их в sw.js
 * (toString), поэтому замыканий и внешних констант внутри быть не должно.
 */

/** Никогда не кэшируем: авторизация, скачивание файлов, WS, S3 (presigned), health. */
export const isNeverCachedRequest = ({
  url,
  sameOrigin,
  request,
}: {
  url: URL
  sameOrigin: boolean
  request: Request
}): boolean => {
  if (request.headers.has('range')) return true // частичные ответы (аудио) не кэшируем
  const p = url.pathname
  if (/^\/(ws|s3|health)(\/|$)/.test(p)) return true
  if (!sameOrigin) return /\/s3\//.test(p) // presigned-ссылки S3 могут быть на другом хосте
  if (!p.startsWith('/api/')) return false
  return p.startsWith('/api/auth/') || p.includes('/download')
}

/** GET /api/* (кроме исключённых выше) — NetworkFirst. */
export const isCacheableApiRequest = ({
  url,
  sameOrigin,
  request,
}: {
  url: URL
  sameOrigin: boolean
  request: Request
}): boolean => {
  if (!sameOrigin || !url.pathname.startsWith('/api/')) return false
  if (request.headers.has('range')) return false
  return !(url.pathname.startsWith('/api/auth/') || url.pathname.includes('/download'))
}

export const pwaOptions: Partial<VitePWAOptions> = {
  // Только «prompt»: новая версия ждёт решения пользователя (тост «Доступна новая версия»),
  // без молчаливого skipWaiting на активной сессии.
  registerType: 'prompt',
  injectRegister: false, // регистрируем сами через virtual:pwa-register/react (useRegisterSW)
  includeAssets: ['favicon.svg', 'icons/apple-touch-icon.png'],
  manifest: {
    name: 'MERIDIAN AI',
    short_name: 'MERIDIAN',
    lang: 'ru',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    background_color: '#080A0F',
    theme_color: '#080A0F',
    icons: [
      { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
      { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
      { src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml' },
    ],
  },
  workbox: {
    globPatterns: ['**/*.{js,css,html,svg,png,woff2,webmanifest}'],
    cleanupOutdatedCaches: true,
    navigateFallback: '/index.html',
    navigateFallbackDenylist: [
      /^\/api(\/|$)/,
      /^\/ws(\/|$)/,
      /^\/s3(\/|$)/,
      /^\/health(\/|$)/,
      /^\/desktop\/latest\.json$/,
    ],
    runtimeCaching: [
      // Порядок важен: первое совпавшее правило побеждает.
      { urlPattern: isNeverCachedRequest, handler: 'NetworkOnly' },
      {
        urlPattern: isCacheableApiRequest,
        handler: 'NetworkFirst',
        method: 'GET',
        options: {
          cacheName: API_CACHE_NAME,
          networkTimeoutSeconds: 5,
          expiration: { maxEntries: 50, maxAgeSeconds: 24 * 60 * 60 },
        },
      },
    ],
  },
}
