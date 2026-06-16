import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Уникальный id сборки. vite.config исполняется на сборочной машине,
// поэтому Date.now() здесь корректен. Зашивается в бандл (define) и
// пишется в dist/version.json — рантайм сравнивает их для детекта обновления.
const BUILD_ID = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'meridian-version-json',
      apply: 'build',
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'version.json',
          source: JSON.stringify({ buildId: BUILD_ID }),
        })
      },
    },
  ],
  define: {
    __BUILD_ID__: JSON.stringify(BUILD_ID),
  },
})
