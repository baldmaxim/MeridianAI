import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Отдельно от vite.config.ts: в тестах не нужен PWA-плагин (virtual:pwa-register не собирается).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
})
